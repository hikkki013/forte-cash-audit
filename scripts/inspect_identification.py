"""Local visual inspection / detector probe; never changes production rules."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw
from forte.vision import sampled_frames, Detector, PROMPTS, draw_boxes
from forte.pipeline import cropped_detections


def main():
    p = argparse.ArgumentParser()
    p.add_argument('video')
    p.add_argument('--output', required=True)
    p.add_argument('--probe', action='store_true')
    p.add_argument('--interval', type=float, default=1)
    p.add_argument('--zone', type=float, nargs=4, default=[.18, .36, .68, .60])
    p.add_argument('--labels', nargs='+', default=['id_card', 'passport', 'cash', 'phone'])
    p.add_argument('--separate', action='store_true')
    p.add_argument('--start', type=float, default=0)
    a = p.parse_args()
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    detector = Detector('models/grounding-dino-tiny') if a.probe else None
    PROMPTS.update({'id_card': 'an identity card', 'passport': 'a passport'})
    frames, rows = [], []
    for t, im in sampled_frames(a.video, a.interval):
        if t < a.start: continue
        w, h = im.size
        zone = a.zone
        details = []
        if detector:
            people = detector.detect(im, ['person'])
            queries = [[label] for label in a.labels] if a.separate else [a.labels]
            details = [d for query in queries for d in cropped_detections(detector, im, zone, query)]
            rows.append({'t': t, 'size': [w,h], 'people': people, 'details': details})
            print(t, details, flush=True)
        crop = im.crop(tuple(int(v*s) for v,s in zip(zone,[w,h,w,h])))
        if detector:
            crop = draw_boxes(crop, [{**d,'box':[d['box'][0]-int(zone[0]*w),d['box'][1]-int(zone[1]*h),d['box'][2]-int(zone[0]*w),d['box'][3]-int(zone[1]*h)]} for d in details])
        tile = Image.new('RGB', (540, 390), 'white')
        im.thumbnail((210, 365)); tile.paste(im,(0,25))
        crop.thumbnail((330, 340)); tile.paste(crop,(210,25))
        ImageDraw.Draw(tile).text((5,5), f'{t:.2f} sec', fill='black')
        frames.append(tile)
        if len(frames)==12:
            save_sheet(frames,out,len(rows) if detector else int(t))
            frames=[]
    if frames: save_sheet(frames,out,'last')
    if detector: (out/'probe.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')


def save_sheet(frames,out,name):
    sheet=Image.new('RGB',(540*3,390*((len(frames)+2)//3)),'#ccc')
    for i,frame in enumerate(frames): sheet.paste(frame,((i%3)*540,(i//3)*390))
    sheet.save(out/f'sheet-{name}.jpg')


if __name__=='__main__': main()
