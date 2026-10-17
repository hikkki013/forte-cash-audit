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
        return [e for e in events if e["rule_id"] in self.config["enabled_rules"]]
