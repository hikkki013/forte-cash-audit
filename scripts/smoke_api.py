"""Real-model, real-video API smoke test. Results stay in local outputs."""
import argparse
import json
from pathlib import Path
import time
from fastapi.testclient import TestClient
from forte.api import create_app

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--videos',type=Path,required=True)
    args=p.parse_args()
    source=next(f for f in args.videos.glob('*.mov') if f.stem.upper().replace('Х','X')=='X-26')
    out=Path('outputs/api-smoke')
    out.mkdir(parents=True,exist_ok=True)
    with TestClient(create_app(api_key='test-only-local',upload_dir='runtime/smoke-uploads')) as c:
        with source.open('rb') as video:
            r=c.post('/api/v1/analyze',headers={'X-API-Key':'test-only-local'},files={'file':(source.name,video,'video/quicktime')})
        assert r.status_code==202,r.text
        until=time.monotonic()+250
        while time.monotonic()<until:
            j=c.get('/api/v1/jobs/'+r.json()['job_id'],headers={'X-API-Key':'test-only-local'}).json()
            if j['status']!='processing': break
            time.sleep(.5)
        assert j['status']=='done',j
        assert j['result']['violations'], 'Expected candidate event in development X-26'
        (out/'response.json').write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/'openapi.json').write_text(json.dumps(c.app.openapi(),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':j['status'],'verdict':j['result']['verdict'],'events':len(j['result']['violations']),**j['result']['meta']}))
    assert not list(Path('runtime/smoke-uploads').iterdir())

if __name__=='__main__': main()
