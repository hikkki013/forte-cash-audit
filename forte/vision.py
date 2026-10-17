"""Grounding DINO adapter; inference loads local safetensors only."""
from pathlib import Path
import time

PROMPTS = {
    "person": "a person",
    "cash": "banknotes",
    "bag": "a bag",
    "phone": "a mobile phone",
    "coat": "a coat",
    "jacket": "a jacket",
    "safe_open": "an open metal cabinet",
    "safe_closed": "a closed metal cabinet",
    "door_open": "an open door",
    "door_closed": "a closed door",
    "cup": "a cup",
    "food": "food",
    "screen": "a computer screen",
    "notebook": "a notebook",
    "coin_container": "a coin tray",
    "container": "a small container",
    "laptop": "a laptop",
    "coins": "coins",
}


class Detector:
    def __init__(self, model_dir, device="auto", threshold=0.25, image_size=640):
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        self.torch = torch
        self.device = "cuda" if device == "auto" and torch.cuda.is_available() else ("cpu" if device == "auto" else device)
        if not Path(model_dir).is_dir():
            raise FileNotFoundError("Local model missing. Run python -m scripts.download_model first.")
        self.processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(
            model_dir, local_files_only=True, use_safetensors=True).to(self.device).eval()
        self.threshold = threshold
        self.image_size = image_size
        if self.device == "cuda":
            torch.cuda.reset_peak_memory_stats()

    def detect(self, image, labels=None):
        labels = labels or list(PROMPTS)
        prompt = ". ".join(PROMPTS[k] for k in labels) + "."
        inputs = self.processor(images=image, text=prompt, return_tensors="pt",
            size={"shortest_edge": self.image_size, "longest_edge": 1024}).to(self.device)
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=self.threshold, text_threshold=0.25,
            target_sizes=[image.size[::-1]])[0]
        raw_labels = result.get("text_labels", result.get("labels"))
        rows = []
        for box, score, raw in zip(result["boxes"].tolist(), result["scores"].tolist(), raw_labels):
            # Only exact prompt labels; concatenated ambiguous labels are not facts.
            matches = [k for k in labels if str(raw).strip() in {PROMPTS[k], PROMPTS[k].removeprefix("a ").removeprefix("an ")}]
            if len(matches) == 1:
                rows.append({"label": matches[0], "score": round(score, 4), "box": [round(v, 2) for v in box]})
        return rows

    def memory_mb(self):
        return round(self.torch.cuda.max_memory_allocated()/1024**2, 1) if self.device == "cuda" else None


def sampled_frames(path, interval=1.0, deadline=None):
    """Stream decoded frames with original PTS; never materialize the whole video."""
    import av
    if interval <= 0:
        raise ValueError("interval must be positive")
    next_at = 0.0
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("No video stream")
        stream = container.streams.video[0]
        start = float(stream.start_time * stream.time_base) if stream.start_time else 0.0
        for frame in container.decode(stream):
            if deadline and time.monotonic() > deadline:
                raise TimeoutError("Processing exceeded time budget")
            if frame.time is None:
                continue
            t = float(frame.time) - start
            if t + 1e-6 < next_at:
                continue
            yield round(t, 3), frame.to_image().convert("RGB")
            next_at = t + interval


def draw_boxes(image, detections):
    from PIL import ImageDraw
    out = image.copy()
    draw = ImageDraw.Draw(out)
    for d in detections:
        b = d["box"]
        draw.rectangle(b, outline="red", width=2)
        draw.text((b[0], max(0, b[1]-12)), f'{d["label"]} {d["score"]:.2f}', fill="red")
    return out
