"""Small temporal rules. Facts are observations, never video IDs or known labels."""
from dataclasses import dataclass


@dataclass
class Observation:
    timestamp: float
    cashier: bool
    client: bool
    cash: bool
    safe_open: bool | None = None
    person_near_safe: bool = False
    cash_box: list | None = None
    at_exit: bool = False
    phone_at_cashier: bool = False
    clothing_on_desk: bool = False
    food_at_cashier: bool = False
    door_open: bool | None = None
    camera_degraded: bool = False
    screen_active: bool | None = None


def iou(a, b):
    if a is None or b is None:
        return 0.0
    w = max(0, min(a[2], b[2])-max(a[0], b[0]))
    h = max(0, min(a[3], b[3])-max(a[1], b[1]))
    inter = w*h
    union = max(0, a[2]-a[0])*max(0, a[3]-a[1])+max(0,b[2]-b[0])*max(0,b[3]-b[1])-inter
    return inter/union if union else 0.0


class RuleEngine:
    def __init__(self, config):
        self.config = config
        self.last_t = None
        self.seen_cashier = False
        self.absent_since = self.safe_since = None
        self.absence_fired = self.safe_fired = False
        self.client_seen = False
        self.client_count = 0
        self.client_absence = None
        self.departed = False
        self.previous_cash_box = None
        self.exit_seen = False
        self.windows = {}
        self.window_fired = set()
        self.service_exit_seen = False
        self.missing_counts = {}
        self.hit_counts = {}
        self.screen_work_seen = False
        self.screen_work_hits = 0
        self.screen_exit_seen = False

    def update(self, o):
        events = []
        if self.last_t is not None and o.timestamp <= self.last_t:
            raise ValueError("Timestamps must increase")
        if self.last_t is not None and o.timestamp-self.last_t > self.config["sample_seconds"]*2.5:
            # No invented persistence across missing/undecodable sections.
            self.absent_since = self.safe_since = self.client_absence = None
            self.departed = self.client_seen = self.seen_cashier = False
            self.client_count = 0
            self.previous_cash_box = None
            self.absence_fired = self.safe_fired = False
            self.exit_seen = False
            self.windows.clear()
            self.window_fired.clear()
            self.service_exit_seen = False
            self.missing_counts.clear()
            self.hit_counts.clear()
            self.screen_work_seen = False
            self.screen_work_hits = 0
            self.screen_exit_seen = False
        self.last_t = o.timestamp
        self.seen_cashier |= o.cashier
        if self.seen_cashier and not o.cashier and o.cash:
            self.exit_seen |= o.at_exit
            if self.absent_since is None:
                self.absent_since = o.timestamp
            if (o.timestamp-self.absent_since >= self.config["absence_seconds"] and not self.absence_fired
                    and (self.exit_seen or not self.config.get("require_exit",False))):
                events.append({"rule_id":"cash_unattended", "timecode_sec":self.absent_since,
                    "confirmed_at":o.timestamp, "duration_sec":round(o.timestamp-self.absent_since,3)})
                self.absence_fired = True
        else:
            self.absent_since = None
            self.absence_fired = False
            self.exit_seen = False

        if o.safe_open is True and not o.person_near_safe:
            if self.safe_since is None:
                self.safe_since = o.timestamp
            if o.timestamp-self.safe_since >= self.config["safe_seconds"] and not self.safe_fired:
                events.append({"rule_id":"safe_left_open", "timecode_sec":self.safe_since,
                    "confirmed_at":o.timestamp, "duration_sec":round(o.timestamp-self.safe_since,3)})
                self.safe_fired = True
        else:
            self.safe_since = None
            self.safe_fired = False

        if not o.cash or (self.previous_cash_box is not None and iou(o.cash_box,self.previous_cash_box) < .35):
            self.departed = False
            self.previous_cash_box = None
        if o.client:
            self.client_count += 1
            if self.departed and self.client_count >= 2 and o.cash and o.cashier:
                events.append({"rule_id":"prev_client_cash", "timecode_sec":o.timestamp-self.config["sample_seconds"],
                    "confirmed_at":o.timestamp, "duration_sec":0})
                self.departed = False
            if self.client_count >= 2:
                self.client_seen = True
            self.client_absence = None
        else:
            self.client_count = 0
            if self.client_absence is None:
                self.client_absence = o.timestamp
            if self.client_seen and o.timestamp-self.client_absence >= 2 and o.cash:
                self.departed = True
                self.previous_cash_box = o.cash_box
                self.client_seen = False
        if o.cashier or not o.client:
            self.service_exit_seen = False
        else:
            self.service_exit_seen |= o.at_exit
        if o.cashier:
            self.screen_exit_seen = False
            self.screen_work_hits = self.screen_work_hits + 1 if o.screen_active is True else 0
            self.screen_work_seen = self.screen_work_hits >= 2
        elif self.screen_work_seen:
            self.screen_exit_seen |= o.at_exit
        # Unknown/dark frames cannot establish persistence. A screen-specific
        # departure does not depend on cash, a client, or a known video label.
        screen_condition = (self.screen_work_seen and not o.cashier
                            and o.screen_active is True and not o.camera_degraded)
        conditions = {
            "pc_not_shutdown": (screen_condition, self.config.get("screen_absence_seconds",5)),
            "left_during_service": (self.seen_cashier and o.client and not o.cashier
                and self.service_exit_seen, self.config.get("service_absence_seconds", 5)),
            "phone_with_camera": (o.cashier and o.phone_at_cashier, 3),
            "personal_items": (o.clothing_on_desk, 5),
            "food_at_workplace": (o.cashier and o.food_at_cashier, 5),
            "door_open": (o.door_open is True, 5),
            "camera_obstructed": (o.camera_degraded, 2),
        }
        for rule_id, (condition, seconds) in conditions.items():
            if not condition:
                # One missed object detection may be tolerated, not a long gap.
                # Never fire on an absent detection, and require multiple positive frames.
                misses = self.missing_counts.get(rule_id,0)+1
                self.missing_counts[rule_id] = misses
                if rule_id in {"phone_with_camera","food_at_workplace","personal_items"} and misses <= 1:
                    continue
                self.windows.pop(rule_id, None)
                self.window_fired.discard(rule_id)
                self.hit_counts.pop(rule_id,None)
                continue
            self.missing_counts[rule_id] = 0
            self.hit_counts[rule_id] = self.hit_counts.get(rule_id,0)+1
            since = self.windows.setdefault(rule_id, o.timestamp)
            if o.timestamp-since >= seconds and rule_id not in self.window_fired and self.hit_counts[rule_id] >= 3:
                if rule_id == "pc_not_shutdown" and not self.screen_exit_seen:
                    continue
                events.append({"rule_id":rule_id,"timecode_sec":since,
                    "confirmed_at":o.timestamp,"duration_sec":round(o.timestamp-since,3)})
                self.window_fired.add(rule_id)
        return [e for e in events if e["rule_id"] in self.config["enabled_rules"]]
