"""Local diagnostic contact sheet. Never publish its private frames."""
from pathlib import Path
import argparse
from PIL import Image, ImageDraw
from forte.vision import sampled_frames


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--videos',type=Path,required=True)
    parser.add_argument('--out',type=Path,default=Path('outputs/multi-rule-inspection'))
    args=parser.parse_args()
    root,out=args.videos,args.out
    out.mkdir(parents=True,exist_ok=True)
    tiles=[]
    for ident,times in [(26,[0,4,8]),(40,[10,17,22]),(46,[5,11,17]),(20,[0,5,9])]:
        frames=dict(sampled_frames(root/f'Х-{ident}.mov',1))
        for t in times:
            image=frames[min(frames,key=lambda x:abs(x-t))].copy()
            image.thumbnail((280,510))
            tile=Image.new('RGB',(280,535),'white')
            tile.paste(image,(0,25))
            ImageDraw.Draw(tile).text((5,5),f'X-{ident} @ {t}s',fill='black')
            tiles.append(tile)
    sheet=Image.new('RGB',(840,2140),'white')
    for i,tile in enumerate(tiles):
        sheet.paste(tile,((i%3)*280,(i//3)*535))
    sheet.save(out/'frames.jpg')


if __name__=='__main__':
    main()
