"""Explicit coverage: missing recognizers must never imply compliance."""
import math
from forte.rule_metadata import rule_metadata


def rule_checks(catalog, enabled, events, observable, frames, sample_seconds=1):
    checks = []
    event_ids = {e["rule_id"] for e in events}
    for rule_id, rule in catalog.items():
        duration = {"cash_unattended":3,"prev_client_cash":5,"safe_left_open":5,
            "left_during_service":5,"personal_items":5,"phone_with_camera":3,
            "door_open":5,"camera_obstructed":2,"food_at_workplace":5,"pc_not_shutdown":5,
            "possible_incomplete_cash_return":5,"bag_left_by_employee":3,
            "bag_left_by_visitor":2,"several_clients":2,"desk_materials_left":3,"key_left_in_lock":3}.get(rule_id,0)
        required_frames = max(3, math.ceil(duration/sample_seconds)+1)
        if rule["mode"] == "manual_review":
            status, reason = "not_implemented", rule["limits"]
        elif rule_id not in enabled:
            status, reason = "disabled", "Автоматический поиск этого признака выключен в профиле."
        elif rule_id in event_ids:
            status, reason = "candidate", "Найден визуальный кандидат. Подтвердите его вручную. " + rule["limits"]
        elif observable.get(rule_id, 0) < required_frames or frames < required_frames:
            status, reason = "insufficient_evidence", "Недостаточно различимых наблюдений для оценки. " + rule["limits"]
        else:
            status, reason = "not_detected", "Признак не найден на выбранных кадрах. Это не доказательство соблюдения правила. " + rule["limits"]
        checks.append({"rule_id":rule_id,"title":rule["title"],"status":status,
            "reason":reason,**rule_metadata(rule),"mode":rule["mode"],"review_required":True,
            "observed_frames":observable.get(rule_id,0),
            "event_times_sec":[e["timecode_sec"] for e in events if e["rule_id"]==rule_id]})
    return checks
