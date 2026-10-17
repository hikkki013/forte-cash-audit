"""Development runs on actual videos; no labels are supplied to the pipeline."""
import argparse
import json
from pathlib import Path
from forte.vision import Detector
from forte.pipeline import Pipeline

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--videos',type=Path,required=True)
    p.add_argument('--ids',default='15,26,40,25,3')
    p.add_argument('--out',type=Path,default=Path('outputs/evaluation'))
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    files={f.stem.upper().replace('Х','X'):f for f in args.videos.glob('*.mov')}
    pipe=Pipeline(Detector('models/grounding-dino-tiny'))
    summaries=[]
    for number in args.ids.split(','):
        vid='X-'+number
        result=pipe.analyze(files[vid])
        (args.out/f'{vid}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        summary={'id':vid,'verdict':result['verdict'],'events':[{k:v for k,v in e.items() if k!='evidence_frames'} for e in result['violations']],**result['meta']}
        summaries.append(summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    (args.out/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    main()
