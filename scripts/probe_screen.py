"""Diagnostic screen localization on supplied videos, not a label lookup."""
import argparse
import json
from pathlib import Path
from forte.vision import Detector, sampled_frames, draw_boxes
from forte.pipeline import cropped_detections

def main():
    p=argparse.ArgumentParser()
    p.add_argument('videos',nargs='+',type=Path)
    args=p.parse_args()
    detector=Detector('models/grounding-dino-tiny')
    out=Path('outputs/screen-inspection'); out.mkdir(parents=True,exist_ok=True)
    for path in args.videos:
        for t,im in sampled_frames(path,8):
            rows=cropped_detections(detector,im,[.35,.30,.85,.60],['screen'])
            print(json.dumps({'video':path.name,'t':t,'size':im.size,'screens':rows},ensure_ascii=False),flush=True)
            draw_boxes(im,rows).save(out/(path.stem+f'-{t}-screen.jpg'))

if __name__=='__main__': main()
