import base64
from collections import deque
import io
import json
from pathlib import Path
import time
from forte.rules import Observation, RuleEngine
from forte.vision import sampled_frames


def in_zone(box, zone, width, height):
    x, y = (box[0]+box[2])/2/width, (box[1]+box[3])/2/height
    return zone[0] <= x <= zone[2] and zone[1] <= y <= zone[3]


def evidence(t, image):
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return {"timestamp_sec":t, "image_base64":base64.b64encode(buf.getvalue()).decode("ascii")}


class Pipeline:
    def __init__(self, detector, config_path="config/scene.json", rules_path="config/rules.json"):
        self.detector = detector
        self.config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        self.catalog = json.loads(Path(rules_path).read_text(encoding="utf-8"))

    def analyze(self, path, deadline=None):
        start = time.monotonic()
        deadline = deadline or start+240
        engine = RuleEngine(self.config)
        ring = deque(maxlen=12)
        events, frames, people_frames, observations = [], 0, 0, []
        for t, image in sampled_frames(path, self.config["sample_seconds"], deadline):
            if time.monotonic() > deadline:
                raise TimeoutError("Video analysis exceeded budget")
            width, height = image.size
            if abs(width/height-self.config["expected_aspect"]) > .04:
                raise ValueError("Unsupported camera aspect. Configure scene zones for this camera.")
            people = self.detector.detect(image, ["person"])
            people = [d for d in people if d["label"] == "person"]
            people_frames += bool(people)
            zone = self.config["desk"]
            crop_box = tuple(int(v*s) for v,s in zip(zone, [width,height,width,height]))
            cropped = image.crop(crop_box)
            # Competing prompts reduce the single-label tendency to call a bag cash.
            objects = self.detector.detect(cropped, ["cash", "bag", "phone", "coat"])
            cash = []
            for d in objects:
                if d["label"] != "cash":
                    continue
                b = d["box"]
                b = [b[0]+crop_box[0],b[1]+crop_box[1],b[2]+crop_box[0],b[3]+crop_box[1]]
                cash.append({**d,"box":b})
            money = max(cash,key=lambda d:d["score"],default=None)
            open_state = None
            if "safe_left_open" in self.config["enabled_rules"]:
                states = self.detector.detect(image,["safe_open","safe_closed"])
                opened = max((d["score"] for d in states if d["label"]=="safe_open" and in_zone(d["box"],self.config["safe"],width,height)),default=0)
                closed = max((d["score"] for d in states if d["label"]=="safe_closed" and in_zone(d["box"],self.config["safe"],width,height)),default=0)
                if abs(opened-closed) > .15:
                    open_state = opened > closed
            o = Observation(t,
                any(in_zone(d["box"],self.config["cashier"],width,height) for d in people),
                any(in_zone(d["box"],self.config["client"],width,height) for d in people),
                bool(money), open_state,
                any(in_zone(d["box"],self.config["safe"],width,height) for d in people),
                money["box"] if money else None,
                any(d["score"]>=.5 and in_zone(d["box"],self.config.get("exit",[0,0,0,0]),width,height) for d in people))
            observations.append({"timestamp_sec":t,"cashier":o.cashier,"client":o.client,"cash":o.cash,
                "safe_open":o.safe_open,"at_exit":o.at_exit,"people":people,"cash_detections":cash})
            ring.append((t,image.copy()))
            for event in engine.update(o):
                rule = self.catalog[event["rule_id"]]
                selected = []
                for target in [max(0,event["timecode_sec"]-1),event["timecode_sec"],t]:
                    chosen = min(ring,key=lambda p:abs(p[0]-target))
                    if all(x[0]!=chosen[0] for x in selected):
                        selected.append(chosen)
                description = rule["description"].format(**event)
                description += f' Основание для проверки: {rule["paragraph"]}, {rule["source"]}. {rule["legal_status"]}'
                events.append({"type":rule["type"],"timecode_sec":event["timecode_sec"],
                    "confirmed_at_sec":event["confirmed_at"],"review_required":True,
                    "description":description,"evidence_frames":[evidence(ts,im) for ts,im in selected]})
            frames += 1
        if not frames:
            raise ValueError("Video has no decodable timestamped frames")
        if not people_frames:
            raise ValueError("No people detected; scene cannot be evaluated")
        return {"verdict":"violation" if events else "no_violation", "violations":events,
            "warnings":["Research prototype. no_violation means no enabled rule triggered, not proof of full compliance.",
                "Fixed zones for supplied camera; new camera angle is not validated.",
                "Bags are not treated as cash. Safe rule disabled unless explicitly configured."],
            "meta":{"model":"grounding-dino-tiny","enabled_rules":self.config["enabled_rules"],
                "sampled_frames":frames,"processing_sec":round(time.monotonic()-start,2),
                "peak_gpu_mb":self.detector.memory_mb()}, "observations":observations}
