"""Exercise the real Flask/Supabase flows using only labeled seed accounts.

Writes retry-safe, net-zero stock checks to the sample facility, and creates an
empty integration-check facility/account for onboarding and tenant-isolation
checks. Generates a recovery link through Admin API; never sends an email.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
from uuid import NAMESPACE_URL, uuid5

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import httpx
from supabase import ClientOptions,create_client
from inventory import create_app
from scripts.seed_supabase import get_admin_key,save_record,SEED_TAG

ORIGIN='http://127.0.0.1:5001'


def run(use_cli=False, shared_sessions=False):
    credentials_path=ROOT/'instance'/'seed-credentials.json'
    credentials=json.loads(credentials_path.read_text(encoding='utf-8'))
    assert credentials['completed'], 'Run seed_supabase.py first.'
    checks=0
    with tempfile.TemporaryDirectory() as folder:
        settings={'DATA_DIRECTORY':folder,'SECRET_KEY':secrets.token_hex(32),'SESSION_BACKEND':'sqlite'}
        if shared_sessions:
            settings.update(SESSION_BACKEND='supabase',SUPABASE_SECRET_KEY=get_admin_key(credentials['project_ref'],use_cli))
        app=create_app(settings)
        def check(condition,label):
            nonlocal checks
            assert condition,label
            checks+=1
        def get(client,path):
            return client.get(path,base_url=ORIGIN)
        def saved(client):
            with client.session_transaction(base_url=ORIGIN) as cookie:
                sid=cookie['sid']
            return sid,app.extensions['session_store'].read(sid)
        def post(client,path,payload):
            return client.post(path,json=payload,base_url=ORIGIN,headers={'X-CSRF-Token':saved(client)[1]['csrf']})
        def state(client):
            response=get(client,'/api/state')
            check(response.status_code==200,'Workspace loads from Supabase')
            return response.json
        def login(account):
            client=app.test_client()
            check(get(client,'/').status_code==302,'Anonymous workspace redirects')
            get(client,'/login')
            response=post(client,'/api/auth/login',{k:account[k] for k in ('email','password')})
            check(response.status_code==200,'Seed account signs in')
            return client
        def action(client,name,payload,status=200):
            response=post(client,'/api/actions/'+name,payload)
            check(response.status_code==status,f'{name} returns expected status {status}: '+str(response.json.get('error','')))
            return response.json.get('state')
        def stock(client,item,kind,quantity,label,**extra):
            return action(client,'stock',{'p_item_id':item['id'],'p_transaction_type':kind,'p_quantity':quantity,
                'p_idempotency_key':str(uuid5(NAMESPACE_URL,'bhc-live-check-v1/'+label)),
                'p_reason':'Integration check; paired movements leave stock unchanged',
                'p_reference_number':'LIVE-CHECK',**extra})
        def direct(client):
            from inventory.services import authenticated_client
            return authenticated_client(app.config,saved(client)[1])
        def quantity(data,item_id):
            return next(i['usable_quantity'] for i in data['items'] if i['id']==item_id)

        admin=login(credentials['accounts']['admin'])
        initial=state(admin)
        check(initial['mode']=='live' and initial['facility']['id']==credentials['facility_id'],'Correct live facility')
        check(len(initial['items'])==19,'19 seeded items present')
        check(len(initial['categories'])==10,'10 seeded categories present')
        api_admin=direct(admin)
        check(all(m['role']=='admin' for m in api_admin.table('facility_memberships').select('role')
            .eq('facility_id',credentials['facility_id']).execute().data),'Only administrator memberships remain')
        if shared_sessions:
            replica=create_app(settings)
            replica_client=replica.test_client()
            replica_client.set_cookie('session',admin.get_cookie('session',domain='127.0.0.1').value,domain='127.0.0.1')
            check(get(replica_client,'/api/state').json['facility']['id']==credentials['facility_id'],
                'Independent Flask instance reads the same authenticated session')
            from concurrent.futures import ThreadPoolExecutor
            sid,_=saved(admin)
            def increment(index):
                store=(app if index%2 else replica).extensions['session_store']
                lease=store.acquire(sid)
                try:
                    record=lease.record
                    record['concurrency_check']=record.get('concurrency_check',0)+1
                    store.finish(lease,sid,record)
                finally:
                    lease.release()
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(increment,range(4)))
            check(saved(admin)[1]['concurrency_check']==4,'Shared session leases prevent lost concurrent updates')
            raw=app.extensions['session_store'].request('GET','/app_server_sessions',
                params={'sid_hash':'eq.'+app.extensions['session_store'].digest(sid),'select':'payload'})
            check('access_token' not in raw[0]['payload'] and credentials['accounts']['admin']['email'] not in raw[0]['payload'],
                'Shared session payload is encrypted in the database')
            try:
                api_admin.rpc('lease_app_session',{'p_sid_hash':'0'*64,'p_owner':str(uuid5(NAMESPACE_URL,'unauthorized-session'))}).execute()
            except Exception as error:
                check(getattr(error,'code','')=='42501','Authenticated users cannot call server-only session RPCs')
            else:
                raise AssertionError('Session RPC was exposed to an authenticated user')
            print('PASS: shared sessions across instances, concurrent writes, encryption, and session RPC isolation.',flush=True)
        medicine=next(i for i in initial['items'] if i['name']=='Paracetamol')
        medicine_batch=next(b for b in initial['batches'] if b['item_id']==medicine['id'] and b['expiry_status']=='usable')
        received=stock(admin,medicine,'receipt',1,'admin-receipt',p_batch_id=medicine_batch['id'])
        replay=stock(admin,medicine,'receipt',1,'admin-receipt',p_batch_id=medicine_batch['id'])
        check(len(received['transactions'])==len(replay['transactions']),'Receipt retry is idempotent')
        issued=stock(admin,medicine,'issue',1,'admin-issue',p_batch_id=medicine_batch['id'])
        check(quantity(issued,medicine['id'])==quantity(initial,medicine['id']),'Admin paired stock operations have zero net effect')
        before=deepcopy(issued['batches'])
        action(admin,'stock',{'p_item_id':medicine['id'],'p_transaction_type':'issue','p_quantity':2**32,
            'p_idempotency_key':secrets.token_hex(16)},400)
        check(state(admin)['batches']==before,'Overspending rolls back all batch changes')
        print('PASS: live login, inventory loading, receipt/issue, retry, and rollback.',flush=True)

        # Exercise catalog create/edit/archive/restore, then delete only this
        # unused test item through the existing guarded RPC (no stock history).
        category=next(c for c in initial['categories'] if c['item_type']=='supply')
        item_fields={'code':'QA-UNUSED-001','name':'Unused integration-check item','item_type':'supply',
            'unit':'piece','expiry_required':False,'low_stock_threshold':1,'category_id':category['id']}
        api=direct(admin)
        prior=api.table('items').select('id').eq('facility_id',credentials['facility_id']).eq('code',item_fields['code']).execute().data
        if not prior:
            data=action(admin,'item',item_fields)
            unused=next(i for i in data['items'] if i['code']==item_fields['code'])['id']
        else:
            unused=prior[0]['id']
        action(admin,'item',{**item_fields,'id':unused,'name':'Updated integration-check item'})
        action(admin,'archive',{'id':unused,'is_archived':True})
        action(admin,'archive',{'id':unused,'is_archived':False})
        api.rpc('delete_unused_item',{'p_facility_id':credentials['facility_id'],'p_item_id':unused}).execute()
        check(len(state(admin)['items'])==19,'Unused catalog test item cleaned up; stock history preserved')
        print('PASS: live catalog edits/archival.',flush=True)

        administrative=create_client(app.config['SUPABASE_URL'],get_admin_key(credentials['project_ref'],use_cli),
            options=ClientOptions(auto_refresh_token=False,persist_session=False))
        if 'qa' not in credentials['accounts']:
            credentials['accounts']['qa']={'email':'onboarding@seed.bhc-inventory.test','password':secrets.token_urlsafe(24)}
            save_record(credentials_path,credentials)
        qa_account=credentials['accounts']['qa']
        users=administrative.auth.admin.list_users(page=1,per_page=1000)
        existing=next((u for u in users if u.email==qa_account['email']),None)
        if not existing:
            existing=administrative.auth.admin.create_user({'email':qa_account['email'],'password':qa_account['password'],
                'email_confirm':True,'user_metadata':{'display_name':'Integration Check Administrator'},
                'app_metadata':{'inventory_seed':SEED_TAG}}).user
        check(existing.app_metadata.get('inventory_seed')==SEED_TAG,'QA account is a labeled fixture')
        qa_account['user_id']=str(existing.id)
        save_record(credentials_path,credentials)
        qa=login(qa_account)
        qa_state=state(qa)
        if qa_state.get('onboarding'):
            check('Make it yours.' in get(qa,'/').text,'First-login facility onboarding is displayed')
            response=post(qa,'/api/facility/register',{'name':'Integration Check Facility (Seed)'})
            check(response.status_code==200,'Facility onboarding commits successfully')
            qa_state=state(qa)
        credentials['qa_facility_id']=qa_state['facility']['id']
        save_record(credentials_path,credentials)
        check(qa_state['items']==[],'New facility starts empty')
        check(api.table('facilities').select('id').eq('id',credentials['qa_facility_id']).execute().data==[],
            'Primary administrator cannot read a foreign facility')
        check(direct(qa).table('items').select('id').eq('facility_id',credentials['facility_id']).execute().data==[],
            'QA administrator cannot read primary inventory')
        action(admin,'switch',{'facility_id':credentials['qa_facility_id']},403)
        print('PASS: real facility onboarding and cross-facility isolation.',flush=True)

        # Admin generates a recovery link but sends no email. Follow its actual
        # Supabase verification redirect to verify the configured allowlist and
        # exchange its real tokens through the application's bound callback.
        callback_client=app.test_client(); get(callback_client,'/login')
        sid,callback_record=saved(callback_client)
        nonce=secrets.token_urlsafe(24)
        callback_record['auth_flow']={'nonce':nonce,'email':qa_account['email'],
            'intent':'recovery','expires':time.time()+300}
        app.extensions['session_store'].write(sid,callback_record)
        callback_url=ORIGIN+'/auth/callback/'+nonce
        generated=administrative.auth.admin.generate_link({'type':'recovery','email':qa_account['email'],
            'options':{'redirect_to':callback_url}})
        link=generated.properties.action_link
        check(urlsplit(link).hostname==urlsplit(app.config['SUPABASE_URL']).hostname,'Recovery link belongs to the configured Supabase project')
        verification=httpx.get(link,follow_redirects=False,timeout=20)
        check(verification.status_code in (302,303),'Supabase recovery verification redirects')
        destination=urlsplit(verification.headers['location'])
        check(destination.netloc==urlsplit(ORIGIN).netloc and destination.path=='/auth/callback/'+nonce,
            'Supabase honors the exact local callback URL')
        tokens=parse_qs(destination.fragment)
        check('access_token' in tokens and 'refresh_token' in tokens,'Verified recovery link returns session tokens')
        check(get(callback_client,destination.path).status_code==200,'Bound callback page loads')
        result=post(callback_client,'/api/auth/callback',{'nonce':nonce,'access_token':tokens['access_token'][0],
            'refresh_token':tokens['refresh_token'][0]})
        check(result.status_code==200 and result.json['redirect']=='/account/password','Recovery callback establishes a restricted recovery session')
        check(get(callback_client,'/').headers['Location']=='/account/password','Recovery requires changing the password first')
        new_password=secrets.token_urlsafe(24)
        qa_account['pending_password']=new_password
        save_record(credentials_path,credentials)
        result=post(callback_client,'/api/auth/password',{'password':new_password,'confirmation':new_password})
        check(result.status_code==200,'Recovery password update succeeds')
        qa_account['password']=new_password; qa_account.pop('pending_password',None)
        save_record(credentials_path,credentials)
        relogin=login(qa_account)
        check(state(relogin)['facility']['id']==credentials['qa_facility_id'],'New password signs in to the existing facility')
        print('PASS: actual recovery redirect, callback binding, password update, and re-login (no emails sent).',flush=True)

        result=post(relogin,'/api/auth/password',{'current_password':'incorrect-test-password',
            'password':secrets.token_urlsafe(24),'confirmation':'mismatch'})
        check(result.status_code==400,'Mismatched password confirmation is rejected')
        next_password=secrets.token_urlsafe(24)
        result=post(relogin,'/api/auth/password',{'current_password':'incorrect-test-password',
            'password':next_password,'confirmation':next_password})
        check(result.status_code==401,'Incorrect current password is rejected')
        qa_account['pending_password']=next_password
        save_record(credentials_path,credentials)
        result=post(relogin,'/api/auth/password',{'current_password':qa_account['password'],
            'password':next_password,'confirmation':next_password})
        check(result.status_code==200,'Signed-in password change verifies the current password')
        qa_account['password']=next_password; qa_account.pop('pending_password',None)
        save_record(credentials_path,credentials)
        final_login=login(qa_account)
        check(state(final_login)['facility']['id']==credentials['qa_facility_id'],'Changed password signs in successfully')
        print('PASS: signed-in password change rejects incorrect credentials and accepts the current password.',flush=True)

        for client in (admin,qa,callback_client,relogin,final_login):
            old_cookie=client.get_cookie('session',domain='127.0.0.1').value
            result=post(client,'/api/auth/logout',{})
            check(result.status_code==200,'Logout succeeds')
            check(get(client,'/api/state').status_code==401,'Protected APIs reject logged-out sessions')
            replay_client=app.test_client(); replay_client.set_cookie('session',old_cookie,domain='127.0.0.1')
            check(get(replay_client,'/api/state').status_code==401,'Replaying a logged-out cookie fails')
        print(f'PASS: {checks} live integration checks. Seed inventory quantities are unchanged.')
        print('Sample and QA credentials are in the ignored instance/seed-credentials.json file.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--use-cli',action='store_true')
    parser.add_argument('--shared-sessions',action='store_true')
    arguments=parser.parse_args()
    run(use_cli=arguments.use_cli,shared_sessions=arguments.shared_sessions)
