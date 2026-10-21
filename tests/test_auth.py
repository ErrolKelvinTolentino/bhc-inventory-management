import re
import secrets
import time
from types import SimpleNamespace

import pytest
from supabase_auth.errors import AuthApiError

from inventory import create_app, services


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING":True,"SECRET_KEY":"auth-tests-only","DATA_DIRECTORY":str(tmp_path),
        "SUPABASE_URL":"https://example.supabase.co","SUPABASE_PUBLISHABLE_KEY":"public-test-key"})


def csrf(client):
    page=client.get('/login')
    return re.search(r'name="csrf-token" content="([^"]+)"',page.text).group(1)


def post(client, action, token, payload=None):
    return client.post('/api/auth/'+action,json=payload or {},headers={'X-CSRF-Token':token})


def record(app, client):
    with client.session_transaction() as cookie:
        sid=cookie['sid']
    return sid, app.extensions['session_store'].read(sid)


def response_for(email='admin@example.test'):
    user=SimpleNamespace(id='user-test-1',email=email)
    return SimpleNamespace(user=user,session=SimpleNamespace(access_token='private-access-token',refresh_token='private-refresh-token',user=user))


class FakeAuth:
    def __init__(self):
        self.calls=[]
        self.response=response_for()

    def sign_in_with_password(self,payload):
        self.calls.append(('login',payload))
        return self.response

    def sign_up(self,payload):
        self.calls.append(('register',payload))
        return SimpleNamespace(user=self.response.user,session=None)

    def sign_out(self,payload):
        self.calls.append(('logout',payload))

    def reset_password_email(self,email,options):
        self.calls.append(('recover',email,options))

    def resend(self,payload):
        self.calls.append(('resend',payload))

    def set_session(self,access,refresh):
        self.calls.append(('callback',access,refresh))
        return self.response

    def update_user(self,payload):
        self.calls.append(('password',payload))


@pytest.fixture
def auth(monkeypatch):
    service=FakeAuth()
    client=SimpleNamespace(auth=service)
    monkeypatch.setattr(services,'new_client',lambda config:client)
    return service


def test_login_rotates_id_and_keeps_tokens_server_side(app,auth):
    client=app.test_client()
    token=csrf(client)
    old_sid, _=record(app,client)
    response=post(client,'login',token,{'email':'admin@example.test','password':'password-value'})
    assert response.status_code==200
    sid,saved=record(app,client)
    assert sid!=old_sid and saved['csrf']!=token
    assert saved['mode']=='live' and saved['auth']['user_id']=='user-test-1'
    assert 'private-access-token' not in response.text and 'private-refresh-token' not in client.get_cookie('session').value
    assert 'auth' not in app.extensions['session_store'].read(old_sid)


def test_logout_invalidates_old_session_even_when_remote_signout_fails(app,auth,monkeypatch):
    client=app.test_client(); token=csrf(client)
    post(client,'login',token,{'email':'admin@example.test','password':'password-value'})
    sid,saved=record(app,client); old_cookie=client.get_cookie('session').value
    def unavailable(*args):
        raise RuntimeError('offline')
    monkeypatch.setattr(services,'authenticated_client',unavailable)
    response=post(client,'logout',saved['csrf'])
    assert response.status_code==200 and client.get('/api/state').status_code==401
    assert 'auth' not in app.extensions['session_store'].read(sid)
    replay=app.test_client(); replay.set_cookie('session',old_cookie)
    assert replay.get('/api/state').status_code==401


def test_signup_stores_callback_intent_without_logging_in(app,auth):
    client=app.test_client(); token=csrf(client)
    response=post(client,'register',token,{'email':'new@example.test','password':'new-password','name':'New Administrator'})
    assert response.status_code==200 and 'message' in response.json
    _,saved=record(app,client)
    assert 'auth' not in saved and saved['auth_flow']['intent']=='signup'
    call=auth.calls[-1][1]
    assert call['options']['email_redirect_to'].endswith('/auth/callback/'+saved['auth_flow']['nonce'])
    assert client.get('/').headers['Location']=='/login'


def test_recovery_and_resend_have_generic_messages(app,auth):
    client=app.test_client(); token=csrf(client)
    for mode in ('recover','resend'):
        response=post(client,mode,token,{'email':'admin@example.test'})
        assert response.status_code==200 and 'If ' in response.json['message']
    assert len(auth.calls)==2


def set_flow(app,client,email='admin@example.test',intent='recovery',expires=None):
    sid,saved=record(app,client)
    nonce=secrets.token_urlsafe(24)
    saved['auth_flow']={'nonce':nonce,'email':email,'intent':intent,'expires':expires if expires is not None else time.time()+60}
    app.extensions['session_store'].write(sid,saved)
    return nonce


def test_callback_requires_matching_browser_flow_and_email(app,auth):
    client=app.test_client(); token=csrf(client)
    nonce=set_flow(app,client)
    payload={'nonce':nonce,'access_token':'a','refresh_token':'r'}
    assert post(client,'callback',token,{**payload,'nonce':'wrong'}).status_code==400
    assert not auth.calls
    auth.response=response_for('someone-else@example.test')
    assert post(client,'callback',token,payload).status_code==400
    assert 'auth' not in record(app,client)[1]
    auth.response=response_for()
    result=post(client,'callback',token,payload)
    assert result.status_code==200 and result.json['redirect']=='/account/password'
    assert record(app,client)[1]['password_recovery']
    assert client.get('/').headers['Location']=='/account/password'
    assert post(client,'callback',record(app,client)[1]['csrf'],payload).status_code==400


def test_expired_callback_does_not_process_tokens(app,auth):
    client=app.test_client(); token=csrf(client)
    nonce=set_flow(app,client,expires=time.time()-1)
    assert post(client,'callback',token,{'nonce':nonce,'access_token':'a','refresh_token':'r'}).status_code==400
    assert not auth.calls
    assert client.get('/auth/callback/'+nonce).status_code==302


def test_password_change_requires_current_password_outside_recovery(app,auth):
    client=app.test_client(); token=csrf(client)
    post(client,'login',token,{'email':'admin@example.test','password':'password-value'})
    saved=record(app,client)[1]
    result=post(client,'password',saved['csrf'],{'password':'new-password','confirmation':'new-password'})
    assert result.status_code==400 and not any(c[0]=='password' for c in auth.calls)
    result=post(client,'password',saved['csrf'],{'password':'new-password','confirmation':'new-password','current_password':'password-value'})
    assert result.status_code==200 and any(c[0]=='password' for c in auth.calls)


def test_invalid_refresh_clears_auth_and_requires_signin(app,auth):
    class Broken:
        def set_session(self,*args):
            raise AuthApiError('Invalid refresh token',400,'refresh_token_not_found')
    auth.set_session=Broken().set_session
    client=app.test_client(); token=csrf(client)
    post(client,'login',token,{'email':'admin@example.test','password':'password-value'})
    response=client.get('/api/state')
    assert response.status_code==401 and response.json['redirect']=='/login'
    assert 'auth' not in record(app,client)[1]


def test_sqlite_connection_is_closed_before_return(app,tmp_path):
    client=app.test_client(); client.get('/login')
    file=tmp_path/'sessions.sqlite3'
    renamed=tmp_path/'renamed.sqlite3'
    file.rename(renamed)
    renamed.rename(file)
