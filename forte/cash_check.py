"""Conservative post-counter check for the known right-hand equipment layout.

Object/hand locations establish visual candidates, never the machine's capabilities,
banknote authenticity, or a proven absence of manual counting. No video identifiers.
"""
from forte.rules import iou
from forte.scene_events import distinct_people


EQUIPMENT_LABELS = ['cash', 'cash_counter', 'cash_detector']


def center(box):
    return ((box[0]+box[2])/2, (box[1]+box[3])/2)


def small_objects(rows, label, width, height, zone, threshold):
    result=[]
    for d in rows:
        b=d['box']
        if d['label']!=label or d['score']<threshold: continue
        if not (.012<(b[2]-b[0])/width<.12 and .006<(b[3]-b[1])/height<.06): continue
        if not (zone[0]+.003<b[0]/width<b[2]/width<zone[2]-.003
                and zone[1]+.002<b[1]/height<b[3]/height<zone[3]-.002): continue
        if not any(iou(b,x['box'])>.4 for x in result): result.append(d)
    return result


class CashCheckTracker:
    def __init__(self, config):
        self.config=config
        self.interval=config['sample_seconds']
        self.reset()

    def reset(self):
        self.last_t=None
        self.anchor=None
        self.anchor_hits=0
        self.device_seen=False
        self.input_at=None
        self.output_at=None
        self.last_output=None
        self.cash_at=None
        self.last_cash_at=None
        self.cash_hits=0
        self.device_hits=0
        self.ambiguous_device=False
        self.observed=0
        self.hand_hits=0
        self.last_hand=None
        self.invalid=False
        self.observable=False
        self.finished=False
        self.state='insufficient_evidence'
        self.evidence_times=[]

    def update(self,t,people,equipment,hands,width,height,degraded=False,front_operator=False):
        if self.last_t is not None and (t<=self.last_t or t-self.last_t>2.5*self.interval):
            self.reset()
        self.last_t=t
        # Only this validated equipment arrangement is supported. Other layouts
        # (including client service with the operator facing away) remain unknown.
        room=[d for d in distinct_people(people,.35) if d['box'][3]/height>.45
              and (d['box'][3]-d['box'][1])/height>.12]
        if degraded or front_operator or len(room)!=1:
            if self.input_at is not None: self.invalid=True
            self.state='unsupported_or_obscured'
            return
        machines=[]
        for d in equipment:
            b=d['box']; x,y=center(b)
            if d['label']=='cash_counter' and d['score']>=.32 and \
                    .45<x/width<.70 and .34<y/height<.53 and \
                    .10<(b[2]-b[0])/width<.24 and .07<(b[3]-b[1])/height<.18:
                machines.append(d)
        if len(machines)!=1:
            if self.input_at is not None: self.invalid=True
            self.state='equipment_not_visible'
            return
        anchor=machines[0]['box']
        if self.anchor is not None and iou(anchor,self.anchor)<.7:
            self.invalid=True
        self.anchor=anchor
        self.anchor_hits+=1
        left,top,right,bottom=anchor
        ah=bottom-top
        for d in equipment:
            x,y=center(d['box'])
            if d['label']=='cash_detector' and d['score']>=.25 and \
                    left<=x<=right and top+.60*ah<=y<=bottom:
                self.device_seen=True
        hz=self.config.get('cash_check_hands',[.27,.34,.67,.52])
        ez=self.config.get('cash_check_search',[.18,.33,.72,.54])
        visible_hands=small_objects(hands,'hand',width,height,hz,.28)
        cash=small_objects(equipment,'cash',width,height,ez,.30)
        # A hand in the feed tray followed by one at the output is a handling
        # sequence, not proof that the device counted or authenticated notes.
        feed=any(left-.045*width<=center(d['box'])[0]<=right and
                 top-.015*height<=center(d['box'])[1]<=top+.28*ah for d in visible_hands)
        take=any(left-.025*width<=center(d['box'])[0]<=right and
                 top+.30*ah<=center(d['box'])[1]<=top+.60*ah for d in visible_hands)
        cash_in_feed=any(left-.045*width<=center(d['box'])[0]<=right and
                         top-.015*height<=center(d['box'])[1]<=top+.28*ah for d in cash)
        if feed and cash_in_feed and self.output_at is not None:
            # This recognizer validates one cycle only. Do not borrow a check
            # from the first cycle or attribute its absence to the next bundle.
            self.invalid=True
        if feed and self.input_at is None:
            self.input_at=t
            self.state='feed_observed'
        if self.input_at is None: return
        if take and t-self.input_at>=2*self.interval:
            if self.output_at is None: self.output_at=t
            self.last_output=t
        # Keep the initial action even before there are enough observations.
        self.evidence_times=[self.input_at]
        if self.output_at is None: return
        self.evidence_times.append(self.output_at)
        self.observed+=1
        self.hand_hits+=bool(visible_hands)
        if visible_hands: self.last_hand=t
        elif self.last_hand is not None and t-self.last_hand>2.5*self.interval:
            self.invalid=True
        desk_cash=[d for d in cash if .20*width<center(d['box'])[0]<left-.02*width
                   and top+.35*ah<center(d['box'])[1]<bottom+.025*height]
        if desk_cash:
            self.cash_hits+=1
            if self.cash_at is None: self.cash_at=t
            self.last_cash_at=t
        if self.last_cash_at is not None:
            self.evidence_times.append(self.last_cash_at)
        device_cash=any(left-.025*width<=center(d['box'])[0]<=right and
                        top+.64*ah<=center(d['box'])[1]<=bottom+.01*height for d in cash)
        device_hand=any(left-.025*width<=center(d['box'])[0]<=right and
                        top+.64*ah<=center(d['box'])[1]<=bottom+.01*height for d in visible_hands)
        self.device_hits+=bool(device_cash)
        self.ambiguous_device|=device_hand or device_cash
        self.state='device_use_observed' if self.device_hits>=2 else 'post_counter_observation'

    def finish(self):
        if self.finished: return []
        self.finished=True
        if self.invalid or self.output_at is None or not self.device_seen or self.anchor_hits<3:
            self.state='insufficient_evidence'
            return []
        if self.device_hits>=2:
            self.observable=True
            self.state='device_use_observed'
            return []
        if self.ambiguous_device:
            self.state='ambiguous_device_use'
            return []
        # Wait until EOF, not a fixed early timeout: a later check suppresses
        # the candidate. A short or occluded tail cannot support absence.
        if self.last_t-self.last_output<5 or self.cash_hits<3 or \
                self.observed<6 or self.hand_hits/self.observed<.6 or len(self.evidence_times)<3:
            self.state='insufficient_evidence'
            return []
        self.observable=True
        self.state='candidate'
        return [{'rule_id':'no_count_check','timecode_sec':self.output_at,
                 'confirmed_at':self.last_t,'duration_sec':self.last_t-self.output_at,
                 'evidence_times':list(self.evidence_times)}]
