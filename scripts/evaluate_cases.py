"""Local diagnostic batch. Video names label reports, never detector decisions."""
import argparse
import json
from pathlib import Path
from forte.pipeline import Pipeline
from forte.vision import Detector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('videos', nargs='+', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pipeline = Pipeline(Detector('models/grounding-dino-tiny'))
    for video in args.videos:
        try:
            result = pipeline.analyze(video)
        except Exception as exc:
            print(f'{video.name}: {type(exc).__name__}: {exc}', flush=True)
            continue
        (args.out/(video.stem+'.json')).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'video':video.name, 'seconds':result['meta']['processing_sec'],
                          'events':[(e['rule_id'],e['timecode_sec']) for e in result['violations']]},
                         ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
