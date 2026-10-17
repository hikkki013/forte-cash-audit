"""Conservative visible-screen heuristic; no inference of OS lock/power state."""
from PIL import ImageStat


def screen_state(image, detections):
    candidates = []
    w, h = image.size
    for d in detections:
        x1,y1,x2,y2 = d['box']
        bw,bh = x2-x1,y2-y1
        if (d['label']=='screen' and d['score'] >= .40 and
                12 <= bw <= w*.25 and 16 <= bh <= h*.20 and
                0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
            candidates.append(d)
    if not candidates:
        return {'active':None,'box':None,'reason':'screen_not_localized'}
    box=max(candidates,key=lambda d:d['score'])['box']
    x1,y1,x2,y2=box
    # Inset avoids the bezel, keyboard and bright wall around a tilted screen.
    dx,dy=(x2-x1)*.30,(y2-y1)*.30
    crop=image.crop((round(x1+dx),round(y1+dy),round(x2-dx),round(y2-dy))).convert('L')
    mean=ImageStat.Stat(crop).mean[0]
    histogram=crop.histogram()
    bright=sum(histogram[110:])/sum(histogram)
    active = True if mean >= 110 and bright >= .65 else (False if mean < 65 and bright < .15 else None)
    return {'active':active,'box':box,'mean':round(mean,2),'bright_fraction':round(bright,3),
            'reason':'bright_screen' if active is True else 'dark_screen' if active is False else 'ambiguous_screen'}
