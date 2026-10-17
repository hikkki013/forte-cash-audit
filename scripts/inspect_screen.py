"""Read-only video sampling for screen-detector calibration; outputs stay local."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw
from forte.vision import sampled_frames

def main():
    p = argparse.ArgumentParser()
    p.add_argument('videos', nargs='+', type=Path)
    p.add_argument('--out', type=Path, default=Path('outputs/screen-inspection'))
    p.add_argument('--interval', type=float, default=2)
    p.add_argument('--page-size', type=int, default=12)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for video in args.videos:
        frames = list(sampled_frames(video, args.interval))
        print(video.name, len(frames), frames[-1][0], flush=True)
        for start in range(0, len(frames), max(1,args.page_size)):
            page = frames[start:start+max(1,args.page_size)]
            sheet = Image.new('RGB', (300*4, 575*((len(page)+3)//4)), 'white')
            for i, (t, image) in enumerate(page):
                image.thumbnail((300, 545))
                x, y = i%4*300, i//4*575
                sheet.paste(image, (x,y+25))
                ImageDraw.Draw(sheet).text((x+5,y+5),f'{video.stem} {t:.1f}s',fill='black')
            sheet.save(args.out/(video.stem+f'-{start:03d}.jpg'))

if __name__ == '__main__':
    main()
