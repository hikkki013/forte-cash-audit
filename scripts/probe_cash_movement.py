"""Local cash-motion diagnostics; paths never supply inference labels."""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageDraw
from forte.vision import Detector,sampled_frames,draw_boxes
from forte.pipeline import cropped_detections

def main():
    p=argparse.ArgumentParser()
    p.add_argument('videos',nargs='+',type=Path)
    p.add_argument('--interval',type=float,default=1)
    p.add_argument('--start',type=float,default=0)
    p.add_argument('--end',type=float,default=float('inf'))
    p.add_argument('--out',type=Path,default=Path('outputs/cash-return-inspection'))
    p.add_argument('--zone',type=float,nargs=4,default=[.06,.38,.78,.81])
    args=p.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    detector=Detector('models/grounding-dino-tiny')
    for path in args.videos:
        rows=[]; tiles=[]
        for t,im in sampled_frames(path,args.interval):
            if t<args.start: continue
            if t>args.end: break
            detections=cropped_detections(detector,im,args.zone,['cash'])
            people=detector.detect(im,['person'])
            rows.append({'t':t,'cash':detections,'people':people})
            tile=draw_boxes(im,detections).crop((20,320,370,680)).resize((350,360))
            ImageDraw.Draw(tile).text((2,2),str(t),fill='red')
            tiles.append(tile)
        sheet=Image.new('RGB',(1400,360*((len(tiles)+3)//4)),'white')
        for i,tile in enumerate(tiles): sheet.paste(tile,(i%4*350,i//4*360))
        sheet.save(args.out/(path.stem+'-cash.jpg'))
        (args.out/(path.stem+'-cash.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'video':path.name,'frames':len(rows),'cash_frames':sum(bool(r['cash']) for r in rows)}),flush=True)

if __name__=='__main__': main()
