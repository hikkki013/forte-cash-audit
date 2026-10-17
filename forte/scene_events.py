"""Temporal object/visitor candidates for calibrated camera layouts, no identity."""
from forte.rules import iou


def distinct_people(people):
    selected=[]
    for p in sorted(people,key=lambda d:d['score'],reverse=True):
        if p['score'] < .45:
            continue
        a=p['box']
        area=max(1,(a[2]-a[0])*(a[3]-a[1]))
        duplicate=False
        for q in selected:
            b=q['box']; inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            if inter/min(area,max(1,(b[2]-b[0])*(b[3]-b[1]))) > .70:
                duplicate=True
        if not duplicate:
            selected.append(p)
    return selected


class SceneEvents:
    def __init__(self, config):
        self.config=config
        self.last_t=None
        self.front=False
        self.layout_hits=0
        self.tracks=[]
        self.windows={}
        self.fired=set()
        self.staff_seen=False
        self.visitor_seen=False
        self.visitor_absent=None
        self.exit_until=-1
        self.previous_cash=[]
        self.departed_at=None
        self.previous_fired=False

    def roles(self,t,people,width,height):
        if self.last_t is not None and (t<=self.last_t or t-self.last_t>2.5*self.config['sample_seconds']):
            self.__init__(self.config)
        self.last_t=t
        self.width,self.height=width,height
        people=distinct_people(people)
        def center(p):
            b=p['box']; return (b[0]+b[2])/2/width,(b[1]+b[3])/2/height
        # Glass reflections are small/high and must not become extra visitors.
        room=[p for p in people if p['box'][3]/height >= .40 and (p['box'][3]-p['box'][1])/height >= .12]
        near=[p for p in room if .25<=center(p)[0]<=.75 and .50<=center(p)[1]<=.76]
        far=[p for p in room if p not in near]
        if not self.front:
            self.layout_hits=self.layout_hits+1 if len(near)==1 and not far else 0
            self.front=self.layout_hits>=2
        if self.front:
            staff=near
            visitors=[p for p in far if p['box'][3]/height>=.425]
        else:
            zone=self.config['cashier']
            staff=[p for p in room if zone[0]<=center(p)[0]<=zone[2] and zone[1]<=center(p)[1]<=zone[3]]
            visitors=[p for p in near if p not in staff]
        exits=[p for p in people if .08<=center(p)[0]<=.25 and .20<=center(p)[1]<=.37
               and (p['box'][3]-p['box'][1])/height>.18]
        return staff,visitors,bool(exits)

    def _window(self,key,t,condition,seconds,events,evidence=None):
        if not condition:
            self.windows.pop(key,None)
            self.fired.discard(key)
            return
        since,hits=self.windows.get(key,(t,0)); hits+=1
        self.windows[key]=(since,hits)
        if t-since>=seconds and hits>=3 and key not in self.fired:
            event={'rule_id':key,'timecode_sec':since,'confirmed_at':t,'duration_sec':t-since}
            if evidence is not None: event['evidence_times']=[evidence,since,t]
            events.append(event); self.fired.add(key)

    def update(self,t,staff,visitors,at_exit,objects,degraded=False):
        events=[]
        if degraded:
            self.tracks=[]; self.windows.clear(); self.fired.clear()
            self.previous_cash=[]; self.departed_at=None; self.visitor_seen=False
            return events
        if at_exit: self.exit_until=t+6
        self.staff_seen |= bool(staff)
        # Match stationary items, never infer their contents from the bag class.
        observed=[]
        for d in objects:
            if d['label'] not in {'bag','cash'} or d['score'] < (.30 if d['label']=='bag' else .25):
                continue
            b=d['box']; bw=(b[2]-b[0])/self.width; bh=(b[3]-b[1])/self.height
            if not (.015<bw<.28 and .006<bh<.20): continue
            match=next((tr for tr in self.tracks if tr['label']==d['label'] and iou(tr['box'],b)>=.40),None)
            if match is None and d['label']=='cash':
                # Short, bounded displacement of a unique bundle. Ambiguous
                # associations are rejected rather than merging two cash piles.
                nearby=[tr for tr in self.tracks if tr['label']=='cash' and t-tr['last']<=2
                        and abs((tr['box'][0]+tr['box'][2]-b[0]-b[2])/2)/self.width<.12
                        and abs((tr['box'][1]+tr['box'][3]-b[1]-b[3])/2)/self.height<.035]
                if len(nearby)==1: match=nearby[0]
            if match is None:
                match={'label':d['label'],'box':b,'first':t,'hits':0,'with_visitor':False,'with_staff':False,
                       'appeared_with_visitor':bool(visitors)}
                self.tracks.append(match)
            elif any(match is item for item in observed):
                continue
            match['last']=t; match['hits']+=1
            if d['label']=='cash': match['box']=b
            match['with_visitor'] |= bool(visitors)
            cx,cy=(b[0]+b[2])/2,(b[1]+b[3])/2
            # A permanently visible desk phone mislabelled as a bag is not
            # evidence that the employee handled a bag. Require spatial contact.
            match['with_staff'] |= any(p['box'][0]<=cx<=p['box'][2] and
                                      p['box'][1]<=cy<=p['box'][3] for p in staff)
            observed.append(match)
        self.tracks=[tr for tr in self.tracks if t-tr['last']<=2*self.config['sample_seconds']]
        bags=[tr for tr in observed if tr['label']=='bag' and tr['hits']>=3 and t-tr['first']>=2]
        staff_bags=[tr for tr in bags if tr['with_staff']]
        visitor_bags=[tr for tr in bags if tr['with_visitor'] and tr['appeared_with_visitor']]
        self._window('bag_left_by_employee',t,bool(staff_bags) and self.staff_seen and not staff
                     and not visitors and t<=self.exit_until,3,events,
                     staff_bags[0]['first'] if staff_bags else None)
        self._window('bag_left_by_visitor',t,bool(visitor_bags) and bool(staff) and not visitors
                     and t<=self.exit_until,2,events,
                     visitor_bags[0]['first'] if visitor_bags else None)
        self._window('several_clients',t,bool(staff) and len(visitors)>=2,2,events)

        cash=[tr for tr in observed if tr['label']=='cash' and tr['hits']>=2]
        if visitors:
            # A new visual visit, not a face/person identity claim.
            retained=[tr for tr in cash if any(tr is previous for previous in self.previous_cash)]
            self._window('prev_client_cash',t,bool(staff) and self.departed_at is not None
                         and bool(retained) and not self.previous_fired,2,events,self.departed_at)
            if any(e['rule_id']=='prev_client_cash' for e in events): self.previous_fired=True
            self.visitor_seen=True
            self.visitor_absent=None
        else:
            self.windows.pop('prev_client_cash',None)
            self.fired.discard('prev_client_cash')
            if self.visitor_absent is None: self.visitor_absent=t
            if self.visitor_seen and t-self.visitor_absent>=2 and t<=self.exit_until:
                self.previous_cash=[tr for tr in cash if tr['with_visitor']]
                self.departed_at=t if self.previous_cash else None
                self.previous_fired=False
                self.visitor_seen=False
        # Expire the departed visit when the actual item track is lost. A later
        # banknote at the same coordinates must not resurrect that visit.
        if self.previous_cash and not any(any(tr is previous for previous in self.previous_cash) for tr in self.tracks):
            self.previous_cash=[]; self.departed_at=None
        return [e for e in events if e['rule_id'] in self.config['enabled_rules']]
