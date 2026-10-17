"""Detector pilot. Does not read ground-truth labels or infer violations."""
import argparse
import json
import time
from collections import Counter
from pathlib import Path
from PIL import Image, ImageDraw
from forte.vision import Detector, sampled_frames, draw_boxes

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--videos", type=Path, required=True)
    p.add_argument("--ids", default="15,26,40,25,3")
    p.add_argument("--interval", type=float, default=3)
    p.add_argument("--out", type=Path, default=Path("outputs/pilot"))
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    detector = Detector("models/grounding-dino-tiny")
    files = {f.stem.upper().replace("Х", "X"): f for f in args.videos.glob("*.mov")}
    reports = []
    for number in args.ids.split(","):
        video_id = "X-" + number
        records, tiles = [], []
        started = time.perf_counter()
        for t, im in sampled_frames(files[video_id], args.interval):
            full = detector.detect(im, ["person", "cash", "bag", "phone", "coat"])
            # Known camera: expanded desk area. Report separately, not ground truth.
            crop_box = (int(im.width*.12), int(im.height*.35), int(im.width*.80), int(im.height*.67))
            crop = im.crop(crop_box)
            local = detector.detect(crop, ["cash", "bag", "phone", "coat"])
            records.append({"timestamp_sec": t, "full": full, "desk_crop": local, "crop_box": crop_box})
            view = draw_boxes(im, full)
            view.thumbnail((232, 424))
            tile = Image.new("RGB", (464, 450), "white")
            tile.paste(view, (0, 22))
            cv = draw_boxes(crop, local)
            cv.thumbnail((232, 300))
            tile.paste(cv, (232, 80))
            ImageDraw.Draw(tile).text((6, 4), f"{video_id}  {t:.2f}s | full / desk crop", fill="black")
            tiles.append(tile)
        sheet = Image.new("RGB", (464*3, 450*((len(tiles)+2)//3)), "#dddddd")
        for i, tile in enumerate(tiles):
            sheet.paste(tile, ((i%3)*464, (i//3)*450))
        sheet.save(args.out / f"{video_id}.jpg", quality=88)
        report = {"id": video_id, "seconds": round(time.perf_counter()-started, 2),
            "frames": len(records), "peak_gpu_mb": detector.memory_mb(),
            "full_counts": dict(Counter(d["label"] for r in records for d in r["full"])),
            "crop_counts": dict(Counter(d["label"] for r in records for d in r["desk_crop"])), "observations": records}
        (args.out/f"{video_id}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        reports.append({k:v for k,v in report.items() if k != "observations"})
        print(json.dumps(reports[-1], ensure_ascii=False), flush=True)
    (args.out/"summary.json").write_text(json.dumps({"device": detector.device,"sampling_sec":args.interval,
        "warning":"Development pilot, not accuracy evaluation; detections are unverified.","videos":reports},indent=2),encoding="utf-8")

if __name__ == "__main__":
    main()
