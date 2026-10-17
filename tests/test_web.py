from fastapi.testclient import TestClient
import pytest
from forte.api import create_app

class Analyzer:
    def analyze(self,path,deadline=None):
        return {"verdict":"no_violation","violations":[],"warnings":["test only"]}

def client(tmp_path, host="127.0.0.1", base="http://127.0.0.1:8000"):
    return TestClient(create_app(Analyzer(),"secret-test",tmp_path),base_url=base,client=(host,12345))

def test_web_assets_and_no_source_exposure(tmp_path):
    with client(tmp_path) as c:
        r=c.get('/')
        assert r.status_code==200 and 'id="fileInput"' in r.text
        for variant in ['with-rules','simple']:
            assert c.get(f'/ui/{variant}/app.js').status_code==200
            assert c.get(f'/ui/{variant}/images/logo.png').status_code==200
            for path in ['main.py','../../runtime/api-key.txt','../api.py']:
                assert c.get(f'/ui/{variant}/{path}').status_code==404
        assert 'secret-test' not in c.get('/ui/with-rules/app.js').text

def test_local_session_cookie_and_upload(tmp_path):
    with client(tmp_path) as c:
        headers={'X-Forte-Local':'1','Origin':'http://127.0.0.1:8000','Sec-Fetch-Site':'same-origin'}
        r=c.post('/api/v1/session',headers=headers)
        assert r.status_code==200 and r.json()=={'ready':True}
        assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
        assert r.headers['cache-control']=='no-store'
        r=c.post('/api/v1/analyze',headers=headers,files={'file':('jury.mp4',b'fake-test-video')})
        assert r.status_code==202
        assert c.get('/api/v1/jobs/'+r.json()['job_id'],headers=headers).status_code==200
        assert c.get('/api/v1/jobs/'+r.json()['job_id']).status_code==403
        assert c.get('/api/v1/jobs/'+r.json()['job_id'],headers={'X-API-Key':'secret-test'}).status_code==200
        assert c.get('/api/v1/jobs/'+r.json()['job_id'],headers={**headers,'X-API-Key':'wrong'}).status_code==401

@pytest.mark.parametrize('headers',[
    {}, {'X-Forte-Local':'1','Origin':'https://evil.example'},
    {'X-Forte-Local':'1','Sec-Fetch-Site':'cross-site'},
    {'X-Forte-Local':'1','Origin':'null'},
])
def test_reject_foreign_bootstrap(tmp_path,headers):
    with client(tmp_path) as c:
        assert c.post('/api/v1/session',headers=headers).status_code==403

@pytest.mark.parametrize('host,base',[
    ('192.168.1.2','http://127.0.0.1:8000'),
    ('127.0.0.1','http://evil.example:8000'),
])
def test_reject_remote_peer_and_rebinding_host(tmp_path,host,base):
    with client(tmp_path,host,base) as c:
        assert c.post('/api/v1/session',headers={'X-Forte-Local':'1'}).status_code==403

def test_foreign_origin_cannot_use_existing_cookie(tmp_path):
    with client(tmp_path) as c:
        assert c.post('/api/v1/session',headers={'X-Forte-Local':'1'}).status_code==200
        assert c.post('/api/v1/analyze',headers={'X-Forte-Local':'1','Origin':'https://evil.example'},files={'file':('x.mov',b'x')}).status_code==403
