"""Local lock-patch comparison, not a general key or lock-rotation detector."""
import numpy as np
from PIL import Image


def gray_frame(image, size):
    return np.asarray(image.resize(tuple(size), Image.Resampling.BILINEAR).convert('L'), dtype=np.float32)


def patch(array, box):
    x1,y1,x2,y2=box
    return array[y1:y2,x1:x2]


def lock_occupied(image, calibration, people):
    if not calibration: return False
    w,h=image.size
    rw,rh=calibration['reference_size']
    x1,y1,x2,y2=calibration['lock_box']
    r=calibration.get('search_radius',8)
    return any(p['score']>=.4 and p['box'][0]<(x2+r)*w/rw and p['box'][2]>(x1-r)*w/rw
               and p['box'][1]<(y2+r)*h/rh and p['box'][3]>(y1-r)*h/rh for p in people)


def align_lock(array, calibration):
    """Register cabinet edges, excluding the lock and all desk/PC pixels."""
    ref=np.asarray(calibration['anchor_values'],dtype=np.float32)
    box=calibration['anchor_box']
    radius=calibration.get('search_radius',8)
    best=None
    for dy in range(-radius,radius+1):
        for dx in range(-radius,radius+1):
            moved=[box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy]
            area=patch(array,moved)
            if area.shape!=ref.shape: continue
            offset=float(np.median(area-ref))
            distance=float(np.mean(np.abs(area-ref-offset)))
            if best is None or distance<best[0]: best=(distance,dx,dy,offset)
    return best


def key_state(image, calibration, people=(), degraded=False):
    unknown={'present':None,'method':'calibrated_lock_patch'}
    if not calibration or degraded: return {**unknown,'reason':'unavailable'}
    w,h=image.size
    rw,rh=calibration['reference_size']
    if w<rw or h<rh or abs(w/h-rw/rh)>.015:
        return {**unknown,'reason':'unsupported_resolution_or_aspect'}
    array=gray_frame(image,(rw,rh))
    match=align_lock(array,calibration)
    if match is None or match[0]>calibration['max_anchor_mae']:
        return {**unknown,'reason':'camera_or_cabinet_not_matched'}
    distance,dx,dy,offset=match
    box=[v+(dx if i%2==0 else dy) for i,v in enumerate(calibration['lock_box'])]
    actual=[box[0]*w/rw,box[1]*h/rh,box[2]*w/rw,box[3]*h/rh]
    # Reject even partial human overlap; a hand at the lock is not a key.
    if any(p['score']>=.4 and p['box'][0]<actual[2]+5 and p['box'][2]>actual[0]-5
           and p['box'][1]<actual[3]+5 and p['box'][3]>actual[1]-5 for p in people):
        return {**unknown,'reason':'person_overlaps_lock','box':actual}
    feature=patch(array,box)-offset
    positive=np.asarray(calibration['present_values'],dtype=np.float32)
    negative=np.asarray(calibration['absent_values'],dtype=np.float32)
    weights=np.asarray(calibration['weights'],dtype=np.float32)
    if feature.shape!=positive.shape: return {**unknown,'reason':'clipped_lock'}
    def error(ref): return float(np.sum(np.abs(feature-ref)*weights)/np.sum(weights))
    pos,neg=error(positive),error(negative)
    margin=abs(pos-neg)
    known=min(pos,neg)<=calibration['max_lock_mae'] and margin>=calibration['min_margin']
    return {'present':(pos<neg) if known else None,'method':'calibrated_lock_patch',
            'reason':'matched' if known else 'ambiguous_lock','box':[round(v,2) for v in actual],
            'anchor_mae':round(distance,2),'present_mae':round(pos,2),'absent_mae':round(neg,2),
            'margin':round(margin,2),'shift':[dx,dy]}


class KeyLeftTracker:
    def __init__(self, sample_seconds=1, absence_seconds=3):
        self.sample_seconds=sample_seconds
        self.absence_seconds=absence_seconds
        self.last_t=None
        self.staff_seen=False
        self.exit_until=-1
        self.since=None
        self.hits=0
        self.fired=False

    def update(self,t,present,staff,visitors,at_exit,degraded=False):
        if self.last_t is not None and (t<=self.last_t or t-self.last_t>2.5*self.sample_seconds):
            self.__init__(self.sample_seconds,self.absence_seconds)
        self.last_t=t
        if degraded:
            self.staff_seen=False; self.exit_until=-1
        self.staff_seen |= bool(staff) and not degraded
        if at_exit and self.staff_seen and not degraded: self.exit_until=t+6
        condition=present is True and self.staff_seen and not staff and not visitors and not degraded
        if not condition:
            self.since=None; self.hits=0; self.fired=False
            return []
        if self.since is None:
            if t>self.exit_until: return []
            self.since=t
        self.hits+=1
        if not self.fired and self.hits>=3 and t-self.since>=self.absence_seconds:
            self.fired=True
            return [{'rule_id':'key_left_in_lock','timecode_sec':self.since,'confirmed_at':t,
                     'duration_sec':t-self.since,'evidence_times':[self.since,(self.since+t)/2,t]}]
        return []
