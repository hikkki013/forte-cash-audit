"""Inspect native pixels around a lock, without AI upscaling or inference."""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw
from forte.vision import sampled_frames


def main():
    p = argparse.ArgumentParser()
    p.add_argument('video', type=Path)
    p.add_argument('--start', type=float, default=5)
    p.add_argument('--end', type=float, default=8)
    p.add_argument('--interval', type=float, default=.1)
    p.add_argument('--zone', type=float, nargs=4, default=[.40, .30, .64, .46])
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if not all(math.isfinite(x) for x in [args.start,args.end,args.interval,*args.zone]):
        p.error('Times and zone coordinates must be finite')
    if args.interval <= 0 or args.start < 0 or args.end < args.start:
        p.error('Require interval > 0 and 0 <= start <= end')
    x1,y1,x2,y2=args.zone
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        p.error('Zone must be a nonempty normalized rectangle')
    args.out.mkdir(parents=True, exist_ok=True)
    tiles = []
    for t, im in sampled_frames(args.video, args.interval):
        if t < args.start:
            continue
        if t > args.end:
            break
        w, h = im.size
        crop = im.crop(tuple(round(v*s) for v,s in zip(args.zone, [w,h,w,h])))
        if not crop.width or not crop.height:
            p.error('Zone is smaller than one source pixel')
        native_size = crop.size
        crop = crop.resize((crop.width*3, crop.height*3), Image.Resampling.NEAREST)
        tile = Image.new('RGB', (crop.width, crop.height+30), 'white')
        tile.paste(crop, (0,30))
        ImageDraw.Draw(tile).text((2,2), f'{t:.3f}s native {native_size}', fill='black')
        tiles.append(tile)
    if not tiles:
        p.error('No timestamped frames in the requested interval')
    for start in range(0,len(tiles),12):
        group=tiles[start:start+12]
        tw,th=group[0].size
        sheet=Image.new('RGB',(tw*4, th*((len(group)+3)//4)), 'white')
        for i,tile in enumerate(group):
            sheet.paste(tile,((i%4)*tw,(i//4)*th))
        target=args.out/f'{args.video.stem}-{start:03d}.png'
        sheet.save(target)
        print(target)


if __name__=='__main__':
    main()
