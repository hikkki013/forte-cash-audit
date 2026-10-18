"""Conservative visual candidate: cash received, no visible document in a visit.

No face recognition, OCR, file names or reference-video lookup. This is not a
determination of identity verification. Incomplete/ambiguous visits stay unknown.
"""
from forte.scene_events import distinct_people
from forte.rules import iou


DOCUMENT_LABELS = ['id_card', 'passport', 'cash', 'phone']


def small_items(rows, width, height, zone, labels, threshold=.25):
    result = []
    for row in rows:
        if row['label'] not in labels or row['score'] < threshold:
            continue
        a,b,c,d = [v/s for v,s in zip(row['box'], [width,height,width,height])]
        # Reject cropped machines, large papers, crop edges and implausible boxes.
        if (zone[0]+.006 < a < c < zone[2]-.006 and
                zone[1]+.003 < b < d < zone[3]-.003 and
                .012 <= c-a <= .12 and .006 <= d-b <= .08):
            result.append(row)
    return result


class IdentificationTracker:
    def __init__(self, config):
        self.config = config
        self.interval = config['sample_seconds']
        self.last_t = None
        self.baseline_hits = 0
        self.visit = None
        self.unknown_visits = 0
        self.assessed_visits = 0
        self.state = 'waiting_for_arrival'
        self.previous_room = []

    @property
    def evidence_times(self):
        if not self.visit:
            return []
        return [self.visit[k] for k in ['incoming_at', 'accepted_at', 'last_cash_at']
                if self.visit.get(k) is not None]

    @property
    def observable(self):
        # A completed visual search is not a certificate of identification.
        return self.assessed_visits > 0 and self.unknown_visits == 0

    def finish(self):
        v = self.visit
        self.visit = None
        if not v:
            return []
        sufficient = (v['eligible'] and v['accepted_at'] is not None and
                      v['handling_hits'] >= 2 and v['cash_hits'] >= 3 and
                      v['last_seen']-v['accepted_at'] >= 3)
        if not sufficient:
            self.state = 'incomplete_visit'
            self.unknown_visits += 1
            return []
        if v['document_hits'] >= 2:
            self.state = 'document_observed'
            self.assessed_visits += 1
            return []
        if v['document_hits'] or v['digital_or_ambiguous']:
            self.state = 'ambiguous_document'
            self.unknown_visits += 1
            return []
        self.state = 'candidate'
        self.assessed_visits += 1
        return [{'rule_id': 'no_client_id', 'timecode_sec': v['accepted_at'],
                 'confirmed_at': v['last_seen'],
                 'duration_sec': v['last_seen']-v['accepted_at'],
                 'evidence_times': [v['incoming_at'],v['accepted_at'],v['last_cash_at']]}]

    def update(self, t, people, cash_rows, document_rows, width, height, degraded=False):
        events = []
        if self.last_t is not None and (t <= self.last_t or t-self.last_t > 2.5*self.interval):
            if self.visit:
                self.unknown_visits += 1
            self.visit = None
            self.baseline_hits = 0
            self.previous_room = []
        self.last_t = t
        if degraded:
            if self.visit:
                self.unknown_visits += 1
            self.visit = None
            self.baseline_hits = 0
            self.previous_room = []
            self.state = 'unobservable'
            return events
        room = [p for p in distinct_people(people, min_score=.30) if p['box'][3]/height >= .40
                and (p['box'][3]-p['box'][1])/height >= .10 and
                (p['score']>=.45 or any(iou(p['box'],q['box'])>=.55 for q in self.previous_room))]
        self.previous_room = room
        staff = [p for p in room if .30 <= (p['box'][0]+p['box'][2])/2/width <= .70
                 and .54 <= (p['box'][1]+p['box'][3])/2/height <= .75]
        visitors = [p for p in room if p not in staff]
        zone = self.config.get('cash_return_search', [.20,.44,.52,.59])
        cash = small_items(cash_rows,width,height,zone,{'cash'},.35)
        if not visitors:
            if self.visit:
                self.visit['missing_hits'] += 1
                if self.visit['missing_hits'] >= 2:
                    events = self.finish()
            else:
                self.baseline_hits = self.baseline_hits+1 if len(staff)==1 and not cash else 0
            return events
        if self.visit is None:
            self.visit = {'eligible': self.baseline_hits >= 2 and len(staff)==1,
                          'incoming_at': None, 'accepted_at': None, 'last_cash_at': None,
                          'track_box': None, 'track_at': None,
                          'handling_hits': 0, 'cash_hits': 0, 'document_hits': 0,
                          'digital_or_ambiguous': False, 'missing_hits': 0, 'last_seen': t}
            self.baseline_hits = 0
        v = self.visit
        if v['missing_hits'] or len(staff)!=1 or len(visitors)!=1:
            # A disappeared visitor may have shown a document outside observation.
            v['eligible'] = False
        v['missing_hits'] = 0
        v['last_seen'] = t
        if len(visitors)!=1 or len(staff)!=1:
            self.state = 'ambiguous_roles'
            return events
        items = small_items(document_rows,width,height,
                            self.config.get('identity_interaction_zone',[.20,.44,.52,.57]),
                            {'id_card','passport','phone'})
        if any(d['label']=='id_card' for d in items):
            v['document_hits'] += 1  # Multiple boxes in one frame are ONE observation.
        if any(d['label'] in {'phone','passport'} and d['score']>=.40
               and not any(iou(d['box'],c['box'])>=.2 for c in cash) for d in items):
            v['digital_or_ambiguous'] = True
        boundary = visitors[0]['box'][3]/height+.012
        incoming = [d for d in cash if (d['box'][1]+d['box'][3])/2/height <= boundary]
        if v['incoming_at'] is None and incoming:
            v['incoming_at'] = t
            v['track_box'] = incoming[0]['box']
            v['track_at'] = t
        if v['incoming_at'] is not None:
            # Bounded continuity of a small object, not identity of banknotes.
            previous = v['track_box']
            linked = [d for d in cash if t-v['track_at'] <= 3*self.interval and
                      abs((d['box'][0]+d['box'][2]-previous[0]-previous[2])/2/width) < .16 and
                      abs((d['box'][1]+d['box'][3]-previous[1]-previous[3])/2/height) < .06]
            linked.sort(key=lambda d:d['score'],reverse=True)
            if linked:
                v['track_box'] = linked[0]['box']
                v['track_at'] = t
                v['cash_hits'] += 1
            for d in linked:
                x,y = (d['box'][0]+d['box'][2])/2,(d['box'][1]+d['box'][3])/2
                s = staff[0]['box']
                if (t > v['incoming_at'] and y/height > boundary+.006 and
                        s[0] <= x <= s[2] and s[1] <= y <= s[3]):
                    v['handling_hits'] += 1
                    if v['accepted_at'] is None:
                        v['accepted_at'] = t
                    v['last_cash_at'] = t
                    break
        self.state = 'observing_visit'
        return events
