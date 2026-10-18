"""Explicit local pixel calibration; training file names are not runtime features."""
import argparse
import json
from pathlib import Path
import numpy as np
from forte.vision import sampled_frames


def feature(image,zone,size=(18,32)):
    w,h=image.size
    box=tuple(int(v*s) for v,s in zip(zone,[w,h,w,h]))
    return np.asarray(image.crop(box).resize(size).convert('L'),dtype=float)


def main():
    p=argparse.ArgumentParser();p.add_argument('--videos',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    # Upper door leaf: avoids people and furniture below the transom.
    zone=[.10,.06,.29,.25]
    rows=[]
    for n,times,state in [(30,[8,10],True),(32,[10,12],True),(33,[8,10],True),
                           (31,[15,18],False),(35,[18,21],False)]:
        for t,im in sampled_frames(a.videos/f'Х-{n}.mov',1):
            if t in times:
                rows.append({'open':state,'values':feature(im,zone).round(1).flatten().tolist()})
    data={'zone':zone,'size':[18,32],'max_mae':14,'margin':4,
          'note':'Known glass-door upper leaf, local 30/31/32/33/35 calibration. Unknown cameras must be rejected.',
          'prototypes':rows}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
