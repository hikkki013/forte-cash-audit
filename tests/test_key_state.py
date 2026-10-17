"""Synthetic lock patches and temporal conditions; not video accuracy metrics."""
import copy
import json
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
from forte.key_state import key_state, KeyLeftTracker

CAL=json.loads(Path('config/key_calibration.json').read_text())


def image_with_lock(present=True,shift=(0,0),brightness=0):
    w,h=CAL['reference_size']
    a=np.full((h,w),140,dtype=np.float32)
    for box,values in [(CAL['anchor_box'],CAL['anchor_values']),
                       (CAL['lock_box'],CAL['present_values'] if present else CAL['absent_values'])]:
        x1,y1,x2,y2=box; dx,dy=shift
        a[y1+dy:y2+dy,x1+dx:x2+dx]=values
    return Image.fromarray(np.uint8(np.clip(a+brightness,0,255))).convert('RGB')


@pytest.mark.parametrize('present',[True,False])
@pytest.mark.parametrize('shift,brightness',[((0,0),0),((3,-2),8),((-3,2),-8)])
def test_local_key_features_not_the_whole_frame(present,shift,brightness):
    result=key_state(image_with_lock(present,shift,brightness),CAL)
    assert result['present'] is present


def test_unknown_camera_small_resolution_and_occlusion_are_not_absence():
    im=image_with_lock()
    assert key_state(im,None)['present'] is None
    assert key_state(im,CAL,degraded=True)['present'] is None
    assert key_state(im.resize((232,424)),CAL)['present'] is None
    assert key_state(Image.new('RGB',im.size,'black'),CAL)['present'] is None
    person={'score':.9,'box':[180,250,220,350]}
    assert key_state(im,CAL,[person])['present'] is None
    assert key_state(im,CAL,[person])['reason']=='person_overlaps_lock'


def test_no_evidence_when_key_classes_ambiguous():
    cal=copy.deepcopy(CAL)
    cal['absent_values']=cal['present_values']
    assert key_state(image_with_lock(),cal)['present'] is None


def step(tr,t,present=True,staff=False,visitors=False,exit=False,degraded=False):
    return tr.update(t,present,staff,visitors,exit,degraded)


def test_key_requires_prior_person_exit_and_three_second_persistence():
    tr=KeyLeftTracker()
    assert not [e for t in range(5) for e in step(tr,t)]
    step(tr,5,staff=True)
    assert not [e for t in range(6,10) for e in step(tr,t)]
    events=[e for t in range(10,18) for e in step(tr,t,exit=t==10)]
    assert len(events)==1 and events[0]['timecode_sec']==10 and events[0]['confirmed_at']==13


@pytest.mark.parametrize('interruption',[{'present':False},{'present':None},{'staff':True},{'visitors':True},{'degraded':True}])
def test_interruption_does_not_accumulate_key_absence(interruption):
    tr=KeyLeftTracker()
    step(tr,0,staff=True)
    step(tr,1,exit=True); step(tr,2)
    assert not step(tr,3,**interruption)
    assert not step(tr,4)
    assert not step(tr,5)


def test_gap_cannot_prove_departure():
    tr=KeyLeftTracker()
    step(tr,0,staff=True); step(tr,1,exit=True)
    assert not [e for t in range(10,18) for e in step(tr,t)]


def test_pipeline_key_event_has_metadata_evidence_and_no_filename_lookup(monkeypatch):
    from forte.pipeline import Pipeline
    import forte.pipeline as module
    class Detector:
        def __init__(self): self.frame=-1
        def detect(self,image,labels):
            if labels!=['person']: return []
            self.frame+=1
            box=[180,250,220,350] if self.frame==0 else ([40,180,105,370] if self.frame==1 else None)
            return [{'label':'person','score':.95,'box':box}] if box else []
        def memory_mb(self): return None
    monkeypatch.setattr(module,'sampled_frames',lambda *a:iter((t,image_with_lock()) for t in range(7)))
    results=[]
    for name in ['unseen.mov','arbitrary.mp4']:
        pipeline=Pipeline(Detector()); pipeline.config['enabled_rules']=['key_left_in_lock']
        results.append(pipeline.analyze(name))
    events=results[0]['violations']
    assert len(events)==1 and events==results[1]['violations']
    assert events[0]['rule_id']=='key_left_in_lock'
    assert events[0]['timecode_sec']==1 and events[0]['confirmed_at_sec']==4
    assert len(events[0]['evidence_frames'])==3
    assert events[0]['paragraph']=='п. 80' and events[0]['requirement']
    assert next(c for c in results[0]['rule_checks'] if c['rule_id']=='key_left_in_lock')['status']=='candidate'


def test_unknown_key_is_insufficient_evidence(monkeypatch):
    from forte.pipeline import Pipeline
    import forte.pipeline as module
    class EmptyDetector:
        def detect(self,*a): return []
        def memory_mb(self): return None
    monkeypatch.setattr(module,'sampled_frames',lambda *a:iter((t,Image.new('RGB',(464,848),'gray')) for t in range(7)))
    pipeline=Pipeline(EmptyDetector()); pipeline.config['enabled_rules']=['key_left_in_lock']
    result=pipeline.analyze('never_opened.mov')
    assert not result['violations']
    check=next(c for c in result['rule_checks'] if c['rule_id']=='key_left_in_lock')
    assert check['status']=='insufficient_evidence' and check['observed_frames']==0
