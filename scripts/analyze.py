import argparse
import json
from pathlib import Path
from forte.vision import Detector
from forte.pipeline import Pipeline

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("video",type=Path)
    p.add_argument("--out",type=Path,default=Path("outputs/result.json"))
    p.add_argument("--scene",default="config/scene.json")
    args = p.parse_args()
    result = Pipeline(Detector("models/grounding-dino-tiny"),args.scene).analyze(args.video)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"verdict":result["verdict"],"events":len(result["violations"]),**result["meta"]},ensure_ascii=False))
