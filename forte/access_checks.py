"""Known-camera entrance and post-departure handling candidates, not identity."""
import numpy as np
from forte.scene_events import distinct_people
from forte.cash_check import center, small_objects


def door_state(image,calibration,people=(),degraded=False):
    unknown={'open':None,'method':'calibrated_door'}
    if not calibration or degraded: return {**unknown,'reason':'unavailable'}
    w,h=image.size; z=calibration['zone']
    box=tuple(int(v*s) for v,s in zip(z,[w,h,w,h]))
    if w<400 or h<700 or abs(w/h-.54717)>.02: return {**unknown,'reason':'unsupported_camera'}
    area=(box[2]-box[0])*(box[3]-box[1])
    for p in people:
        b=p['box']
        overlap=max(0,min(b[2],box[2])-max(b[0],box[0]))*max(0,min(b[3],box[3])-max(b[1],box[1]))
        if p['score']>=.4 and overlap/area>.15: return {**unknown,'reason':'occluded'}
    f=np.asarray(image.crop(box).resize(tuple(calibration['size'])).convert('L'),dtype=float).flatten()
    scores={b:min(float(np.mean(np.abs(f-np.asarray(r['values'])))) for r in calibration['prototypes'] if r['open']==b)
            for b in [True,False]}
    best=min(scores,key=scores.get)
    known=scores[best]<=calibration['max_mae'] and abs(scores[True]-scores[False])>=calibration['margin']
    return {'open':best if known else None,'method':'calibrated_door',
            'reason':'matched' if known else 'unknown_appearance','scores':scores}


class RearEntryTracker:
    def __init__(self,interval=1):
        self.interval=interval; self.last_t=None; self.alone_hits=0
        self.ready=False; self.since=None; self.hits=0; self.fired=False
        self.observable=0
        self.open_at=None

    def update(self,t,people,w,h,front=False,degraded=False,door_open=None):
        if self.last_t is not None and (t<=self.last_t or t-self.last_t>2.5*self.interval): self.__init__(self.interval)
        self.last_t=t
        if front or degraded:
            self.alone_hits=0; self.ready=False; self.since=None; self.hits=0
            self.open_at=None
            return []
        if door_open is True: self.open_at=t
        elif door_open is False: self.open_at=None
        room=[p for p in distinct_people(people,.4) if p['box'][3]/h>.36
              and (p['box'][3]-p['box'][1])/h>.12]
        # Rear-facing service layout only. The initial lone worker is a spatial
        # role; no facial identity or authorization is inferred.
        station=[p for p in room if .27<center(p['box'])[0]/w<.65 and
                 .32<center(p['box'])[1]/h<.54 and p['box'][3]/h>.425]
        if len(room)==1 and len(station)==1:
            self.alone_hits+=1; self.ready|=self.alone_hits>=2
        if not room: self.ready=False; self.alone_hits=0
        entrant=[p for p in room if .08<center(p['box'])[0]/w<.40 and
                 .20<center(p['box'])[1]/h<.43 and p['box'][1]/h<.32]
        pairs=[(s,e) for s in station for e in entrant if s is not e and
               (center(e['box'])[1]<center(s['box'])[1]-.04*h or
                center(e['box'])[0]<center(s['box'])[0]-.12*w)]
        # A second person behind glass is not evidence of entry. Require an
        # observed open leaf; allow only a short occlusion by the entrant.
        condition=(self.ready and bool(pairs) and self.open_at is not None
                   and t-self.open_at<=3*self.interval)
        self.observable+=bool(station)
        if not condition:
            self.since=None; self.hits=0
            return []
        if self.since is None: self.since=t
        self.hits+=1
        if self.hits>=2 and t-self.since>=self.interval and not self.fired:
            self.fired=True
            return [{'rule_id':'outsider_in_cashroom','timecode_sec':self.since,
                     'confirmed_at':t,'duration_sec':t-self.since}]
        return []


class ClientDepartureTracker:
    def __init__(self,config):
        self.config=config; self.interval=config['sample_seconds']
        self.last_t=None; self.client_hits=0; self.cash_hits=0; self.cash_time=None
        self.cash_last=None; self.absent=None; self.exit_at=None; self.hand_hits=0
        self.action_at=None; self.fired=False; self.evidence_times=[]; self.observable=0

    def prepare(self,t,people,cash,w,h,front,at_exit,degraded=False):
        if self.last_t is not None and (t<=self.last_t or t-self.last_t>2.5*self.interval): self.__init__(self.config)
        self.last_t=t
        if not front or degraded:
            self.__init__(self.config); self.last_t=t
            return False
        persons=distinct_people(people,.4)
        staff=[p for p in persons if .25<center(p['box'])[0]/w<.75 and .50<center(p['box'])[1]/h<.76]
        service=[p for p in persons if p not in staff and .27<center(p['box'])[0]/w<.65
                 and .36<center(p['box'])[1]/h<.49 and .27<p['box'][1]/h<.40]
        valid_cash=small_objects(cash,'cash',w,h,self.config.get('cash_continuity_search',[.20,.46,.58,.57]),.30)
        if service:
            # A returning/new client starts a new observation; never borrow a
            # departure from the previous visit.
            if self.absent is not None: self.__init__(self.config); self.last_t=t
            self.client_hits+=1
            if valid_cash:
                self.cash_hits+=1; self.cash_last=t
                if self.cash_time is None: self.cash_time=t
            self.exit_at=None
            self.evidence_times=[self.cash_time] if self.cash_time is not None else []
            return False
        if not staff or self.client_hits<2 or self.cash_hits<2: return False
        if self.absent is None: self.absent=t
        if at_exit and t-self.cash_last<=10 and self.exit_at is None: self.exit_at=t
        if self.cash_time is not None:
            self.evidence_times=[self.cash_time]+([self.exit_at] if self.exit_at is not None else [])
        return self.exit_at is not None and t-self.absent>=self.interval and t-self.cash_last<=15

    def update_action(self,t,equipment,hands,w,h):
        zone=self.config.get('departure_search',[.18,.33,.78,.60])
        hs=small_objects(hands,'hand',w,h,zone,.28)
        machines=[d for d in equipment if d['label']=='cash_counter' and d['score']>=.32
                  and .45<center(d['box'])[0]/w<.77 and .34<center(d['box'])[1]/h<.58
                  and .08<(d['box'][2]-d['box'][0])/w<.30]
        feed=any(b['box'][0]-.03*w<=center(a['box'])[0]<=b['box'][2] and
                 b['box'][1]-.025*h<=center(a['box'])[1]<=b['box'][1]+.36*(b['box'][3]-b['box'][1])
                 for a in hs for b in machines)
        self.observable+=bool(machines and hs)
        if not feed:
            self.action_at=None; self.hand_hits=0
            return []
        if self.action_at is None: self.action_at=t
        self.hand_hits+=1
        self.evidence_times=[self.cash_time,self.exit_at,t]
        if self.hand_hits>=2 and not self.fired:
            self.fired=True
            return [{'rule_id':'count_without_client','timecode_sec':self.action_at,
                     'confirmed_at':t,'duration_sec':t-self.action_at,
                     'evidence_times':list(self.evidence_times)}]
        return []
