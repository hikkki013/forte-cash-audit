"""Explicit development calibration from labelled lock states; never runtime clip lookup."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from forte.vision import sampled_frames
from forte.key_state import gray_frame, patch, align_lock, key_state


def at(path,t):
    return min(sampled_frames(path,1),key=lambda item:abs(item[0]-t))[1]


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--present',type=Path,required=True)
    p.add_argument('--absent',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--present-time',type=float,default=16)
    p.add_argument('--absent-time',type=float,default=14)
    p.add_argument('--check',nargs='*',type=Path,default=[])
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    reference=at(args.absent,args.absent_time)
    size=list(reference.size)
    if size != [464,848]:
        p.error('This explicit calibration uses the 464x848 reference camera; choose new anchor/lock boxes for another camera.')
    neg=gray_frame(reference,size)
    # Native pixels of the same cabinet only. Anchor excludes the key area.
    anchor=[186,262,235,291]
    lock=[190,294,207,319]
    cal={'reference_size':size,'anchor_box':anchor,'lock_box':lock,'search_radius':8,
         'max_anchor_mae':8,'max_lock_mae':14,'min_margin':5,
         'anchor_values':patch(neg,anchor).round(2).tolist(),
         'provenance':'Development calibration: labelled inserted key and empty lock. Known cabinet/camera only; no independent accuracy claim.'}
    pos=gray_frame(at(args.present,args.present_time),size)
    distance,dx,dy,offset=align_lock(pos,cal)
    positive=patch(pos,[v+(dx if i%2==0 else dy) for i,v in enumerate(lock)])-offset
    negative=patch(neg,lock)
    # Restrict discriminative pixels to the lock neighbourhood, not the cabinet/desk.
    weights=np.zeros(positive.shape,dtype=np.float32)
    weights[4:17,2:14]=np.maximum(np.abs(positive-negative)[4:17,2:14]-8,0)
    if weights.sum()<20: raise ValueError('No discriminative key pixels')
    cal.update(present_values=positive.round(2).tolist(),absent_values=negative.round(2).tolist(),
               weights=weights.round(2).tolist())
    (args.out/'calibration.json').write_text(json.dumps(cal),encoding='utf-8')
    sheet=Image.new('RGB',(510,280),'white')
    for i,(label,feature) in enumerate([('present',positive),('absent',negative),('weights',weights*5)]):
        im=Image.fromarray(np.uint8(np.clip(feature,0,255))).resize((170,250),Image.Resampling.NEAREST)
        sheet.paste(im,(170*i,30)); ImageDraw.Draw(sheet).text((170*i,0),label,fill='black')
    sheet.save(args.out/'features.png')
    for path in [args.present,args.absent,*args.check]:
        rows=[{'t':t,**key_state(im,cal)} for t,im in sampled_frames(path,1)]
        (args.out/(path.stem+'.json')).write_text(json.dumps(rows),encoding='utf-8')
        print(path.name,[(r['t'],r['present'],r.get('present_mae'),r.get('absent_mae'),r.get('reason')) for r in rows],flush=True)


if __name__=='__main__': main()
