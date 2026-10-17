"""Experimental post-departure desk-material check; no file-name labels."""
from forte.rules import iou

LABELS = ['notebook', 'coin_container', 'container', 'laptop', 'coins']
ITEM_NAMES = {'notebook': 'блокнот', 'possible_coin_container': 'ёмкость, предположительно с монетами'}


def desk_materials(rows, width, height, zone):
    """Reject clipped detections, laptop/notebook ambiguity and large equipment."""
    accepted = []
    laptops = [d for d in rows if d['label']=='laptop' and d['score']>=.35]
    coins = [d for d in rows if d['label']=='coins' and d['score']>=.25]
    for d in rows:
        x1,y1,x2,y2 = d['box']
        bw,bh = (x2-x1)/width,(y2-y1)/height
        if not (x1/width>zone[0]+.003 and x2/width<zone[2]-.003 and
                y1/height>zone[1]+.003 and y2/height<zone[3]-.003):
            continue
        if d['label']=='notebook' and d['score']>=.45 and .04<bw<.20 and .015<bh<.09:
            if not any(iou(d['box'],p['box'])>.20 for p in laptops):
                accepted.append(d)
        elif d['label']=='container' and d['score']>=.30 and .012<bw<.06 and .01<bh<.045:
            # The generic tray label often lands on the counting machine.
            # Only a small container with spatially coincident coin evidence qualifies.
            accepted.append({**d,'label':'small_container',
                             'coin_evidence':any(iou(d['box'],c['box'])>.25 for c in coins)})
    return accepted


class DeskClearTracker:
    def __init__(self, sample_seconds=1):
        self.sample_seconds=sample_seconds
        self.last_t=None
        self.tracks=[]
        self.exit_until=-1
        self.fired=False

    def update(self,t,staff,visitors,at_exit,items,degraded=False):
        if self.last_t is not None and (t<=self.last_t or t-self.last_t>2.5*self.sample_seconds):
            self.__init__(self.sample_seconds)
        self.last_t=t
        if degraded:
            self.tracks=[]; self.exit_until=-1; self.fired=False
            return []
        if staff or visitors:
            self.fired=False
        if at_exit:
            self.exit_until=t+6
        self.tracks=[tr for tr in self.tracks if t-tr['last']<=2*self.sample_seconds]
        observed=[]
        for d in items:
            if d['label'] not in {'notebook','small_container'}:
                continue
            tr=next((tr for tr in self.tracks if tr['label']==d['label'] and iou(tr['box'],d['box'])>=.4),None)
            if tr is None:
                tr={'label':d['label'],'box':d['box'],'first':t,'last':t,'hits':0,'coin_hits':0,'with_staff':False,'since':None,'absent_hits':0}
                self.tracks.append(tr)
            if any(tr is previous for previous in observed):
                continue
            tr['last']=t; tr['hits']+=1; tr['with_staff'] |= bool(staff)
            tr['coin_hits']+=bool(d.get('coin_evidence'))
            observed.append(tr)
        for tr in self.tracks:
            eligible=tr['label']=='notebook' or tr['coin_hits']>=3
            condition=(eligible and any(tr is o for o in observed) and tr['with_staff'] and tr['hits']>=3 and
                       not staff and not visitors and t<=self.exit_until)
            if not condition:
                tr['since']=None; tr['absent_hits']=0
            else:
                if tr['since'] is None: tr['since']=t
                tr['absent_hits']+=1
        ready=[tr for tr in observed if tr['since'] is not None and t-tr['since']>=3 and tr['absent_hits']>=4]
        if not ready or self.fired:
            return []
        self.fired=True
        since=min(tr['since'] for tr in ready)
        return [{'rule_id':'desk_materials_left','timecode_sec':since,'confirmed_at':t,
                 'detected_items':sorted({'possible_coin_container' if tr['label']=='small_container' else tr['label'] for tr in ready}),
                 'evidence_times':[min(tr['first'] for tr in ready),since,t]}]
