"""Replay saved detector observations after rule-only changes (not new inference)."""
import argparse
import json
from pathlib import Path
from forte.pipeline import in_zone
from forte.rules import Observation,RuleEngine

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,default=Path('outputs/evaluation-v2'))
    args=p.parse_args()
    cfg=json.loads(Path('config/scene.json').read_text())
    rows=[]
    for path in sorted(args.input.glob('X-*.json')):
        result=json.loads(path.read_text(encoding='utf-8'))
        engine=RuleEngine(cfg)
        events=[]
        for obs in result['observations']:
            cash=max(obs['cash_detections'],key=lambda d:d['score'],default=None)
            at_exit=any(d['score']>=.5 and in_zone(d['box'],cfg['exit'],464,848) for d in obs['people'])
            events+=engine.update(Observation(obs['timestamp_sec'],obs['cashier'],obs['client'],obs['cash'],cash_box=cash['box'] if cash else None,at_exit=at_exit))
        rows.append({'id':path.stem,'events':events,'inference_sec':result['meta']['processing_sec']})
    payload={'note':'Development tuning. Rule replay using actual saved v2 detections at 464x848; NOT a held-out evaluation.','videos':rows}
    Path('outputs/rule-replay.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps(payload,indent=2))

if __name__=='__main__':main()
