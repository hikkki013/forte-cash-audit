"""Exercise the same local upload/job API as the UI; never print credentials."""
import argparse
import json
from pathlib import Path
import time
import httpx


def main():
    p=argparse.ArgumentParser()
    p.add_argument('video',type=Path)
    p.add_argument('--out',type=Path,default=Path('outputs/http-check.json'))
    p.add_argument('--port',type=int,default=8000)
    args=p.parse_args()
    if not 1024 <= args.port <= 65535: p.error('Use a local port between 1024 and 65535')
    key=Path('runtime/api-key.txt').read_text().strip()
    with httpx.Client(base_url=f'http://127.0.0.1:{args.port}',headers={'X-API-Key':key},timeout=30) as client:
        with args.video.open('rb') as source:
            response=client.post('/api/v1/analyze',files={'file':('unseen-jury-clip'+args.video.suffix,source,'video/quicktime')})
        response.raise_for_status()
        job=response.json()['job_id']; deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            response=client.get('/api/v1/jobs/'+job); response.raise_for_status()
            result=response.json()
            if result['status'] in {'done','failed'}: break
            time.sleep(1)
        else: raise TimeoutError('Local API job did not finish in 300 seconds')
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        if result['status']!='done': raise RuntimeError(result.get('error','analysis_failed'))
        events=result['violations']
        print(json.dumps({'status':result['status'],'verdict':result['verdict'],
                          'events':[(e['rule_id'],e['timecode_sec'],len(e['evidence_frames'])) for e in events]},
                         ensure_ascii=False))


if __name__=='__main__': main()
