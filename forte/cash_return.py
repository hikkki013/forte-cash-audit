"""Visual residual-cash + return sequence, never a cash-count/theft verdict.

This prototype supports the front-operator layout only. Roles come from the
initial lone seated person, then the visitor across the desk, not faces/IDs.
"""
from forte.rules import iou


class CashReturnTracker:
    def __init__(self, config):
        self.config=config
        self.last_t=None
        self.layout_hits=0
        self.front_operator=False
        self._reset_episode()

    def _reset_episode(self):
        self.started=None
        self.client_edge=None
        self.incoming=False
        self.handling_hits=0
        self.tracks=[]
        self.return_hits=0
        self.return_since=None
        self.fired=False
        self.no_pair_since=None

    @staticmethod
    def _center(d):
        b=d['box']; return ((b[0]+b[2])/2,(b[1]+b[3])/2)

    def prepare(self,t,people,width,height):
        if self.last_t is not None and (t<=self.last_t or t-self.last_t>self.config['sample_seconds']*2.5):
            self._reset_episode(); self.front_operator=False; self.layout_hits=0
        self.last_t=t
        self.width,self.height=width,height
        strong=[p for p in people if p['score']>=.45]
        self.near=[p for p in strong if .30<=self._center(p)[0]/width<=.70 and .54<=self._center(p)[1]/height<=.75]
        self.far=[p for p in strong if .15<=self._center(p)[0]/width<=.60 and .32<=self._center(p)[1]/height<=.48]
        if not self.front_operator:
            self.layout_hits=self.layout_hits+1 if len(self.near)==1 and not self.far else 0
            self.front_operator=self.layout_hits>=2
        pair=self.front_operator and len(self.near)==1 and len(self.far)==1
        if not pair:
            self.no_pair_since=t if self.no_pair_since is None else self.no_pair_since
            if t-self.no_pair_since>=3: self._reset_episode()
            self.return_hits=0; self.return_since=None
            return False
        self.no_pair_since=None
        if self.started is not None and t-self.started>30:
            self._reset_episode()
        if self.started is None:
            self.started=t
            self.client_edge=self.far[0]['box'][3]/height
        return True

    def update(self,t,detections):
        w,h=self.width,self.height
        zone=self.config.get('cash_return_search',[.20,.44,.52,.59])
        boxes=[]
        for d in detections:
            b=[v/s for v,s in zip(d['box'],[w,h,w,h])]
            bw,bh=b[2]-b[0],b[3]-b[1]
            # Reject cropped counter edges/counting machine hallucinations.
            if (d['label']=='cash' and d['score']>=.25 and .012<=bw<=.12 and .006<=bh<=.08
                    and .35<=bw/bh<=5 and b[0]>zone[0]+.006 and b[2]<zone[2]-.006
                    and b[1]>zone[1]+.003 and b[3]<zone[3]-.003):
                boxes.append(b)
        boundary=self.client_edge+.012
        client_boxes=[b for b in boxes if (b[1]+b[3])/2<=boundary]
        staff_boxes=[b for b in boxes if (b[1]+b[3])/2>boundary+.006]
        if not self.incoming:
            self.incoming=bool(client_boxes)
            return []
        if staff_boxes:
            self.handling_hits+=1
        for b in staff_boxes:
            match=next((track for track in self.tracks if iou(track['box'],b)>=.50),None)
            if match:
                match['last']=t; match['hits']+=1
            else:
                self.tracks.append({'box':b,'first':t,'last':t,'hits':1})
        self.tracks=[track for track in self.tracks if t-track['first']<=30]
        residual=next((track for track in self.tracks if track['hits']>=2 and
            track['last']-track['first']>=3 and
            t-track['last']<=(self.config['sample_seconds']*1.1 if self.return_hits else 0)),None)
        if self.handling_hits>=3 and client_boxes and residual:
            self.return_hits+=1
            if self.return_since is None: self.return_since=t
            if self.return_hits>=2 and not self.fired:
                self.fired=True
                return [{'rule_id':'possible_incomplete_cash_return','timecode_sec':self.return_since,
                    'confirmed_at':t,'duration_sec':t-self.return_since,
                    'evidence_times':[residual['first'],self.return_since,t]}]
        else:
            self.return_hits=0; self.return_since=None
        return []
