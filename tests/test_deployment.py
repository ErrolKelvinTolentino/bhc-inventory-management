"""Deployment boundaries: no local writes, mandatory secrets, and fail-closed sessions."""
import json
from pathlib import Path

import pytest

from inventory import create_app
from inventory.shared_sessions import SessionUnavailable, SupabaseSessionStore


def production_config(tmp_path, **overrides):
    return {"VERCEL":True,"APP_URL":"https://inventory.example.test", "SESSION_BACKEND":"supabase",
        "SECRET_KEY":"test-secret-key-which-is-at-least-32-characters",
        "SUPABASE_URL":"https://example.supabase.co","SUPABASE_PUBLISHABLE_KEY":"public-test-key",
        "SUPABASE_SECRET_KEY":"sb_secret_test-only", "DATA_DIRECTORY":str(tmp_path/'must-not-exist'),**overrides}


def test_vercel_boots_without_writing_local_files(tmp_path):
    app=create_app(production_config(tmp_path))
    assert not (tmp_path/'must-not-exist').exists()
    assert isinstance(app.extensions['session_store'],SupabaseSessionStore)
    assert app.config['SESSION_COOKIE_SECURE']
    client=app.test_client()
    response=client.get('/health',base_url='https://inventory.example.test')
    assert response.status_code==200 and response.json=={'status':'ok'}
    assert not response.headers.get('Set-Cookie')
    assert client.get('/health',base_url='https://foreign.example.test').status_code==400


@pytest.mark.parametrize('overrides',[
    {'SESSION_BACKEND':'sqlite'}, {'SECRET_KEY':''}, {'SECRET_KEY':'short'},
    {'APP_URL':'http://inventory.example.test'}, {'APP_URL':'https://inventory.example.test/path'},
    {'SUPABASE_SECRET_KEY':''}, {'SUPABASE_PUBLISHABLE_KEY':''}, {'SUPABASE_URL':''},
])
def test_vercel_requires_safe_runtime_configuration(tmp_path,overrides):
    with pytest.raises(RuntimeError):
        create_app(production_config(tmp_path,**overrides))
    assert not (tmp_path/'must-not-exist').exists()


def test_shared_session_failure_does_not_open_demo_or_live_workspace(tmp_path,monkeypatch):
    app=create_app(production_config(tmp_path))
    def unavailable(*args,**kwargs):
        raise SessionUnavailable('Session storage is temporarily unavailable.')
    monkeypatch.setattr(app.extensions['session_store'],'rpc',unavailable)
    client=app.test_client()
    response=client.get('/api/state',base_url='https://inventory.example.test')
    assert response.status_code==503 and 'error' in response.json
    assert 'items' not in response.json


def test_shared_session_payload_encryption_and_domain_separation(tmp_path):
    store=SupabaseSessionStore(production_config(tmp_path))
    other=SupabaseSessionStore(production_config(tmp_path,SECRET_KEY='another-secret-key-of-at-least-32-characters'))
    payload=store.cipher.encrypt(json.dumps({'auth':{'access_token':'private-token'}}).encode()).decode()
    assert 'private-token' not in payload
    assert store.decode(payload)['auth']['access_token']=='private-token'
    with pytest.raises(SessionUnavailable):
        other.decode(payload)


def test_shared_session_commit_failure_returns_service_unavailable(tmp_path,monkeypatch):
    app=create_app(production_config(tmp_path))
    store=app.extensions['session_store']
    def rpc(name,**kwargs):
        if name=='lease_app_session':
            return {'acquired':True,'payload':None}
        if name=='commit_app_session':
            raise SessionUnavailable('Session storage is temporarily unavailable.')
    monkeypatch.setattr(store,'rpc',rpc)
    response=app.test_client().get('/login',base_url='https://inventory.example.test')
    assert response.status_code==503
    assert response.headers['Cache-Control']=='no-store'


def test_https_proxy_preserves_csrf_origin_and_secure_cookie(tmp_path,monkeypatch):
    app=create_app(production_config(tmp_path))
    store=app.extensions['session_store']
    encrypted=store.cipher.encrypt(json.dumps({'csrf':'proxy-test-token'}).encode()).decode()
    def rpc(name,**kwargs):
        if name=='lease_app_session':
            return {'acquired':True,'payload':encrypted}
    monkeypatch.setattr(store,'rpc',rpc)
    response=app.test_client().post('/api/auth/login',base_url='http://inventory.example.test',
        headers={'X-Forwarded-Proto':'https','Origin':'https://inventory.example.test','X-CSRF-Token':'proxy-test-token'},
        json={'email':'invalid'})
    assert response.status_code==400 and response.json['error']=='Enter a valid email address.'
    cookie=response.headers['Set-Cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie


def test_deployment_build_excludes_local_credentials():
    config=json.loads(Path('vercel.json').read_text())
    assert config['framework']=='flask'
    assert config['functions']['app.py']['maxDuration']<180
    assert 'instance/**' in config['functions']['app.py']['excludeFiles']
    assert '.env*' in config['functions']['app.py']['excludeFiles']
    assert 'instance' in Path('.vercelignore').read_text().splitlines()
