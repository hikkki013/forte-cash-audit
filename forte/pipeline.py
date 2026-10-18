"""Local multi-rule visual candidate search with explicit per-rule coverage."""
import base64
from collections import deque, Counter
import io
import json
from pathlib import Path
import time
from PIL import ImageStat
from forte.rules import Observation, RuleEngine
from forte.vision import sampled_frames
from forte.coverage import rule_checks
from forte.screen import screen_state
from forte.cash_return import CashReturnTracker
from forte.scene_events import SceneEvents
from forte.safe_state import calibrated_safe_state
from forte.rule_metadata import rule_metadata
from forte.key_state import key_state, lock_occupied, KeyLeftTracker
from forte.desk_clear import DeskClearTracker, desk_materials, LABELS as DESK_LABELS, ITEM_NAMES
from forte.identification import IdentificationTracker, DOCUMENT_LABELS
from forte.cash_check import CashCheckTracker, EQUIPMENT_LABELS
from forte.access_checks import door_state, RearEntryTracker, ClientDepartureTracker

def in_zone(box, zone, width, height):
    x, y = (box[0]+box[2])/2/width, (box[1]+box[3])/2/height
    return zone[0] <= x <= zone[2] and zone[1] <= y <= zone[3]


def center_inside(box, outer):
    x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
    return outer[0] <= x <= outer[2] and outer[1] <= y <= outer[3]


def cropped_detections(detector, image, zone, labels):
    w, h = image.size
    bounds = tuple(int(v*s) for v,s in zip(zone,[w,h,w,h]))
    rows = detector.detect(image.crop(bounds), labels)
    return [{**d,"box":[d["box"][0]+bounds[0],d["box"][1]+bounds[1],
                        d["box"][2]+bounds[0],d["box"][3]+bounds[1]]} for d in rows]


def state_in_zone(detections, prefix, zone, width, height):
    scores = [max((d["score"] for d in detections
                   if d["label"] == prefix+"_"+s and in_zone(d["box"],zone,width,height)),default=0)
              for s in ["open","closed"]]
    if max(scores) < .35 or abs(scores[0]-scores[1]) < .15:
        return None
    return scores[0] > scores[1]


def frame_quality(image):
    stats = ImageStat.Stat(image.resize((64,64)).convert("L"))
    mean, spread = stats.mean[0], stats.stddev[0]
    return (mean < 12 and spread < 12) or (mean > 245 and spread < 5)


def evidence(t, image):
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return {"timestamp_sec":t, "image_base64":base64.b64encode(buf.getvalue()).decode("ascii")}


def rendered_event(event, rule, frames):
    selected = []
    for target in event.get('evidence_times', [max(0,event['timecode_sec']-1),
                                              event['timecode_sec'],event['confirmed_at']]):
        chosen = min(frames,key=lambda p:abs(p[0]-target))
        if all(x[0]!=chosen[0] for x in selected):
            selected.append(chosen)
    description = rule['description'] + ' ' + rule['limits']
    if event['rule_id']=='desk_materials_left':
        names=', '.join(ITEM_NAMES[k] for k in event['detected_items'])
        description=f'После ухода сотрудника на столе остались: {names}. ' + rule['limits']
    if event['rule_id']=='pc_not_shutdown':
        description = (f"После ухода сотрудника из рабочей зоны экран оставался визуально активным "
            f"не менее {event['duration_sec']:g} с; наблюдалось движение человека в зоне выхода. "
            "Это признак возможного оставления компьютера активным без присмотра. " + rule['limits'])
    result = {'type':rule['event_title'],'rule_id':event['rule_id'],'title':rule['event_title'],
              'timecode_sec':event['timecode_sec'],'confirmed_at_sec':event['confirmed_at'],
              'review_required':True,'classification':'visual_candidate',**rule_metadata(rule),
              'description':description,'evidence_frames':[evidence(ts,im) for ts,im in selected]}
    if 'detected_items' in event:
        result['detected_items']=event['detected_items']
    return result


class Pipeline:
    def __init__(self, detector, config_path="config/scene.json", rules_path="config/rules.json"):
        self.detector = detector
        self.config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        self.catalog = json.loads(Path(rules_path).read_text(encoding="utf-8"))
        calibration_name=self.config.get('safe_calibration')
        calibration=Path(config_path).parent/calibration_name if calibration_name else None
        self.safe_calibration=json.loads(calibration.read_text(encoding='utf-8')) if calibration and calibration.is_file() else None
        key_name=self.config.get('key_calibration')
        key_path=Path(config_path).parent/key_name if key_name else None
        self.key_calibration=json.loads(key_path.read_text(encoding='utf-8')) if key_path and key_path.is_file() else None
        door_name=self.config.get('door_calibration')
        door_path=Path(config_path).parent/door_name if door_name else None
        self.door_calibration=json.loads(door_path.read_text(encoding='utf-8')) if door_path and door_path.is_file() else None
        unknown = set(self.config["enabled_rules"]) - set(self.catalog)
        if unknown:
            raise ValueError("Unknown configured rules")
        if any(self.catalog[k]["mode"] != "automatic_candidate" for k in self.config["enabled_rules"]):
            raise ValueError("Manual-review rules cannot be enabled as visual detectors")

    def analyze(self, path, deadline=None):
        start = time.monotonic()
        deadline = deadline or start+240
        engine = RuleEngine({**self.config,'enabled_rules':[r for r in self.config['enabled_rules'] if r!='prev_client_cash']})
        scene_events = SceneEvents(self.config)
        desk_clear = DeskClearTracker(self.config['sample_seconds'])
        key_tracker = KeyLeftTracker(self.config['sample_seconds'])
        ring = deque(maxlen=32)
        cash_return = CashReturnTracker(self.config)
        identification = IdentificationTracker(self.config)
        identity_frames = {}
        cash_check = CashCheckTracker(self.config)
        cash_check_frames = {}
        rear_entry=RearEntryTracker(self.config['sample_seconds'])
        departure=ClientDepartureTracker(self.config)
        departure_frames={}
        events, frames, observations = [], 0, []
        observable = Counter()
        enabled = set(self.config["enabled_rules"])
        for t, image in sampled_frames(path, self.config["sample_seconds"], deadline):
            if time.monotonic() > deadline:
                raise TimeoutError("Video analysis exceeded budget")
            width, height = image.size
            if abs(width/height-self.config["expected_aspect"]) > .04:
                raise ValueError("Unsupported camera aspect. Configure scene zones for this camera.")
            degraded = frame_quality(image)
            observable["camera_obstructed"] += 1
            people, objects, states, clothing_objects = [], [], [], []
            screens = []
            if not degraded:
                people = [d for d in self.detector.detect(image,["person"]) if d["label"] == "person"]
                if "pc_not_shutdown" in enabled:
                    screens = cropped_detections(self.detector,image,
                        self.config.get("screen_search",[.35,.30,.85,.60]),["screen"])
                objects = cropped_detections(self.detector,image,self.config["desk"],
                    ["cash","bag","phone","coat","jacket","cup","food"])
                if "personal_items" in enabled:
                    # Fewer competing labels improve small folded-clothing detection.
                    clothing_objects = cropped_detections(self.detector,image,self.config["desk"],
                        ["coat","bag","phone"])
                if enabled & {"safe_left_open","door_open"}:
                    # Explicit open/closed competition; no detection is UNKNOWN, never closed.
                    states = cropped_detections(self.detector,image,[.05,.12,.8,.62],
                        ["safe_open","safe_closed","door_open","door_closed"])
            cashiers = [d for d in people if in_zone(d["box"],self.config["cashier"],width,height)]
            clients = [d for d in people if d not in cashiers and in_zone(d["box"],self.config["client"],width,height)]
            scene_staff,scene_clients,scene_exit=scene_events.roles(t,people,width,height)
            door_details=door_state(image,self.door_calibration,people,degraded)
            door = door_details['open'] if self.door_calibration else state_in_zone(states,"door",self.config.get("door",self.config["exit"]),width,height)
            rear_events=[]
            if 'outsider_in_cashroom' in enabled:
                rear_events=rear_entry.update(t,people,width,height,scene_events.front,degraded,door)
            check_equipment,check_hands=[],[]
            if 'no_count_check' in enabled:
                if not degraded and people and not scene_events.front:
                    check_equipment=cropped_detections(self.detector,image,
                        self.config.get('cash_check_search',[.18,.33,.72,.54]),EQUIPMENT_LABELS)
                    if any(d['label']=='cash_counter' for d in check_equipment):
                        check_hands=cropped_detections(self.detector,image,
                            self.config.get('cash_check_hands',[.27,.34,.67,.52]),['hand'])
                cash_check.update(t,people,check_equipment,check_hands,width,height,
                                  degraded,scene_events.front)
                if t in cash_check.evidence_times:
                    cash_check_frames[t]=image.copy()
                cash_check_frames={ts:im for ts,im in cash_check_frames.items()
                                   if ts in cash_check.evidence_times}
            material_rows=[]
            materials=[]
            material_events=[]
            if 'desk_materials_left' in enabled:
                if not degraded:
                    zone=self.config.get('desk_material_search',[.23,.40,.67,.56])
                    material_rows=cropped_detections(self.detector,image,zone,DESK_LABELS)
                    materials=desk_materials(material_rows,width,height,zone)
                material_events=desk_clear.update(t,scene_staff,scene_clients,scene_exit,materials,degraded)
            if scene_events.front:
                cashiers,clients=scene_staff,scene_clients
            detail_cash=[]
            if not degraded and scene_events.front and enabled & {'prev_client_cash','count_without_client'}:
                zone=self.config.get('cash_continuity_search',[.20,.46,.58,.57])
                detail_cash=cropped_detections(self.detector,image,zone,['cash'])
                # Clipped counting machines and crop borders are not banknotes.
                detail_cash=[d for d in detail_cash if d['score']>=.30 and
                    d['box'][0]/width>zone[0]+.006 and d['box'][2]/width<zone[2]-.006 and
                    d['box'][1]/height>zone[1]+.003 and d['box'][3]/height<zone[3]-.003 and
                    (d['box'][3]-d['box'][1])/height<.06]
            cash = [d for d in objects if d["label"]=="cash"]
            departure_events=[]
            departure_equipment,departure_hands=[],[]
            if 'count_without_client' in enabled:
                if departure.prepare(t,people,detail_cash,width,height,scene_events.front,scene_exit,degraded):
                    dz=self.config.get('departure_search',[.18,.33,.78,.60])
                    departure_equipment=cropped_detections(self.detector,image,dz,['cash_counter'])
                    departure_hands=cropped_detections(self.detector,image,dz,['hand'])
                    departure_events=departure.update_action(t,departure_equipment,departure_hands,width,height)
                if t in departure.evidence_times:
                    departure_frames[t]=image.copy()
                departure_frames={ts:im for ts,im in departure_frames.items() if ts in departure.evidence_times}
            money = max(cash,key=lambda d:d["score"],default=None)
            def at_cashier(d):
                return (d["score"] >= .35 and any(center_inside(d["box"],p["box"]) for p in cashiers)
                    and not any(center_inside(d["box"],p["box"]) for p in clients))
            phone = any(d["label"]=="phone" and d['score']>=.50 and at_cashier(d) for d in objects)
            food = any(d["label"] in {"cup","food"} and at_cashier(d) for d in objects)
            # Exclude coats whose centers lie on people: wearing a coat is not storage.
            clothing = any(d["label"] in {"coat","jacket"} and d["score"] >= .3
                and not any(center_inside(d["box"],p["box"]) for p in people) for d in clothing_objects)
            safe_details=calibrated_safe_state(image,self.safe_calibration) if not degraded else {'open':None}
            safe = safe_details['open']
            if safe is None:
                safe_states=[d for d in states if (d['box'][2]-d['box'][0])/width<.32 and
                             (d['box'][3]-d['box'][1])/height<.25]
                safe = state_in_zone(safe_states,"safe",self.config["safe"],width,height)
            screen = screen_state(image,screens)
            return_detections=[]
            return_events=[]
            return_observable=False
            if 'possible_incomplete_cash_return' in enabled:
                return_observable=cash_return.prepare(t,people,width,height)
                if return_observable and not degraded:
                    return_detections=cropped_detections(self.detector,image,
                        self.config.get('cash_return_search',[.20,.44,.52,.59]),['cash'])
                    return_events=cash_return.update(t,return_detections)
            identity_events, identity_rows = [], []
            identity_cash = []
            if 'no_client_id' in enabled:
                if not degraded and people:
                    identity_rows = cropped_detections(self.detector,image,
                        self.config.get('identity_search',[.18,.36,.68,.60]),DOCUMENT_LABELS)
                    # Reuse the exact same localized cash query when it already ran.
                    identity_cash = return_detections if return_observable else cropped_detections(
                        self.detector,image,self.config.get('cash_return_search',[.20,.44,.52,.59]),['cash'])
                identity_events = identification.update(t,people,identity_cash,identity_rows,
                                                         width,height,degraded)
                if t in identification.evidence_times:
                    identity_frames[t] = image.copy()
            o = Observation(t,bool(cashiers),bool(clients),bool(money),safe,
                any(in_zone(d["box"],self.config["safe"],width,height) for d in people),
                money["box"] if money else None,
                any(d["score"] >= .5 and (d["box"][3]-d["box"][1])/height > .18
                    and in_zone(d["box"],self.config.get("exit",[0,0,0,0]),width,height) for d in people),
                phone,clothing,food,door,degraded,screen['active'])
            if safe_details.get('open') is not None:
                z=self.safe_calibration['zone']
                o.person_near_safe |= any(d['score']>=.45 and d['box'][1]/height<.30 and
                    d['box'][2]/width>z[0] and d['box'][0]/width<z[2] and d['box'][3]/height>z[1]
                    for d in people)
            for key in enabled-{"camera_obstructed","safe_left_open","door_open","pc_not_shutdown","possible_incomplete_cash_return","several_clients","desk_materials_left","key_left_in_lock","no_client_id","no_count_check","outsider_in_cashroom","count_without_client"}:
                observable[key] += bool(people) and not degraded
            observable["safe_left_open"] += safe is not None
            observable["door_open"] += door is not None
            observable["pc_not_shutdown"] += screen['active'] is not None
            observable['possible_incomplete_cash_return'] += return_observable and not degraded
            observable['several_clients'] += scene_events.front and not degraded and bool(scene_staff)
            observable['desk_materials_left'] += bool(materials) and not degraded
            scene_objects=[d for d in objects if d['label']!='cash']+(detail_cash if scene_events.front else cash)
            scene_candidates=scene_events.update(t,scene_staff,scene_clients,scene_exit,scene_objects,degraded)
            key_details={'present':None,'reason':'disabled'}
            key_events=[]
            if 'key_left_in_lock' in enabled:
                key_details=key_state(image,self.key_calibration,people,degraded)
                occupied=lock_occupied(image,self.key_calibration,people)
                key_events=key_tracker.update(t,key_details['present'],occupied or bool(scene_staff),
                    bool(scene_clients),scene_exit or o.at_exit,degraded)
                observable['key_left_in_lock'] += key_details['present'] is not None
            if scene_events.departed_at is not None:
                # Money retained from an earlier visit is not evidence of
                # incomplete return of the current visitor's money.
                return_events=[]
            observations.append({"timestamp_sec":t,"cashier":o.cashier,"client":o.client,"cash":o.cash,
                "safe_open":safe,"door_open":door,"at_exit":o.at_exit,"phone_at_cashier":phone,
                "clothing_on_desk":clothing,"food_at_cashier":food,"camera_degraded":degraded,
                "people":people,"cash_detections":cash,"object_detections":objects,"state_detections":states,
                "clothing_detections":clothing_objects,"screen":screen,"screen_detections":screens,
                "cash_return_observable":return_observable,"cash_return_detections":return_detections})
            observations[-1].update({'front_operator':scene_events.front,'visitor_count':len(scene_clients),
                                     'desk_material_detections':material_rows,'desk_materials':materials,
                                     'cash_continuity_detections':detail_cash,
                                     'safe_calibration':safe_details})
            observations[-1]['key_state']=key_details
            observations[-1]['identification']={'state':identification.state,
                'document_detections':identity_rows,'cash_detections':identity_cash}
            observations[-1]['cash_check']={'state':cash_check.state,
                'equipment_detections':check_equipment,'hand_detections':check_hands,
                'manual_recount':'not_implemented'}
            observations[-1]['door_calibration']=door_details
            observations[-1]['departure_check']={'equipment':departure_equipment,'hands':departure_hands,
                'cash_hits':departure.cash_hits,'absent_since':departure.absent,'exit_at':departure.exit_at}
            ring.append((t,image.copy()))
            for event in engine.update(o)+return_events+scene_candidates+material_events+key_events+rear_events:
                events.append(rendered_event(event,self.catalog[event['rule_id']],ring))
            for event in identity_events:
                events.append(rendered_event(event,self.catalog['no_client_id'],list(identity_frames.items())))
            for event in departure_events:
                events.append(rendered_event(event,self.catalog['count_without_client'],list(departure_frames.items())))
            # Keep at most three exact original frames, including in long visits.
            identity_frames = {ts:im for ts,im in identity_frames.items() if ts in identification.evidence_times}
            frames += 1
        if not frames:
            raise ValueError("Video has no decodable timestamped frames")
        if 'no_client_id' in enabled:
            for event in identification.finish():
                events.append(rendered_event(event,self.catalog['no_client_id'],list(identity_frames.items())))
            observable['no_client_id'] = frames if identification.observable else 0
        if 'no_count_check' in enabled:
            for event in cash_check.finish():
                events.append(rendered_event(event,self.catalog['no_count_check'],list(cash_check_frames.items())))
            observable['no_count_check'] = frames if cash_check.observable else 0
        events.sort(key=lambda e:e['timecode_sec'])
        observable['outsider_in_cashroom']=rear_entry.observable
        observable['count_without_client']=departure.observable
        checks = rule_checks(self.catalog,enabled,events,observable,frames,self.config["sample_seconds"])
        unresolved = sum(c["status"] in {"not_implemented","insufficient_evidence","disabled"} for c in checks)
        # The task specification requires a binary detection verdict, not a
        # compliance certificate. Coverage remains separate from that verdict.
        return {"verdict":"violation" if events else "no_violation",
            "coverage_status":"partial" if unresolved else "complete",
            "violations":events,"rule_checks":checks,
            "warnings":["Результаты — визуальные кандидаты для ручной проверки, не установленное нарушение.",
                "Профиль зон настроен для исходной камеры. Другой ракурс не валидирован.",
                "Отсутствие детекции не доказывает отсутствие предмета или действия.",
                "Для части правил текст пунктов сверен с предоставленным PDF; применимость к событию и актуальность онлайн-редакции не подтверждены."],
            "meta":{"model":"grounding-dino-tiny","enabled_rules":self.config["enabled_rules"],
                "catalog_rules":len(checks),"automatic_rules":len(enabled),"unresolved_rules":unresolved,
                "sampled_frames":frames,"processing_sec":round(time.monotonic()-start,2),
                "peak_gpu_mb":self.detector.memory_mb()},"observations":observations}
