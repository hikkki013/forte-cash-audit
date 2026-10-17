"""Probe localized objects, preserving UNKNOWN when the model sees nothing."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw
from forte.vision import Detector, sampled_frames, draw_boxes, PROMPTS
from forte.pipeline import cropped_detections


def main():
    p = argparse.ArgumentParser()
    p.add_argument('videos', nargs='+', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--interval', type=float, default=3)
    p.add_argument('--zone',type=float,nargs=4,default=[.34,.26,.68,.48])
    p.add_argument('--labels',nargs='+',default=['safe_open','safe_closed'])
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    detector = Detector('models/grounding-dino-tiny')
    PROMPTS.update({'safe_open':'an open safe', 'safe_closed':'a closed safe',
                    'key':'a key', 'envelope':'an envelope', 'elastic':'a rubber band',
                    'notebook':'a notebook', 'coin_container':'a coin tray',
                    'container':'a small container', 'laptop':'a laptop', 'coins':'coins'})
    for path in args.videos:
        rows, tiles = [], []
        for t, im in sampled_frames(path, args.interval):
            zone = args.zone
            detections = cropped_detections(detector, im, zone, args.labels)
            details = cropped_detections(detector, im, zone, ['key']) if 'safe_open' in args.labels else []
            w,h = im.size
            crop = draw_boxes(im,detections+details).crop(tuple(int(v*s) for v,s in zip(zone,[w,h,w,h])))
            crop.thumbnail((350,300))
            tile=Image.new('RGB',(350,330),'white'); tile.paste(crop,(0,25))
            ImageDraw.Draw(tile).text((2,2),str(t),fill='black'); tiles.append(tile)
            rows.append({'t':t,'size':im.size,'states':detections,'keys':details})
        sheet=Image.new('RGB',(1400,330*((len(tiles)+3)//4)),'white')
        for i,tile in enumerate(tiles): sheet.paste(tile,(i%4*350,i//4*330))
        sheet.save(args.out/(path.stem+'.jpg'))
        (args.out/(path.stem+'.json')).write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'video':path.name,'rows':rows},ensure_ascii=False),flush=True)


if __name__=='__main__': main()
