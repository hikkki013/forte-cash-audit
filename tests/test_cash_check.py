"""Post-counter sequence regression without filename-derived decisions."""
import json
from pathlib import Path
import pytest
from PIL import Image
from forte.cash_check import CashCheckTracker, EQUIPMENT_LABELS, small_objects

CFG=json.loads(Path('config/scene.json').read_text(encoding='utf-8'))
PERSON={'label':'person','score':.8,'box':[93,291,193,514]}
MACHINE={'label':'cash_counter','score':.6,'box':[208,333,278,437]}
DEVICE={'label':'cash_detector','score':.5,'box':[210,390,258,437]}
CASH={'label':'cash','score':.6,'box':[150,405,180,420]}
DEVICE_CASH={**CASH,'box':[224,400,250,418]}
FEED={'label':'hand','score':.5,'box':[220,338,242,352]}
TAKE={**FEED,'box':[204,364,225,383]}
REST={**FEED,'box':[150,390,175,410]}
DEVICE_HAND={**FEED,'box':[220,401,245,421]}


def step(tr,t,cash=(),hands=None,equipment=None,**kwargs):
    return tr.update(t,[PERSON],([MACHINE,DEVICE] if equipment is None else equipment)+list(cash),
                     [REST] if hands is None else hands,464,848,**kwargs)


def sequence(tr,end=11):
    for t in range(end):
        step(tr,t,[CASH] if t>=4 else [],[FEED] if t==0 else [TAKE] if t==3 else [REST])


def test_candidate_requires_sequence_and_is_emitted_only_once_at_eof():
    tr=CashCheckTracker(CFG)
    sequence(tr)
    assert not tr.observable
    result=tr.finish()
    assert result==[{'rule_id':'no_count_check','timecode_sec':3,'confirmed_at':10,
                    'duration_sec':7,'evidence_times':[0,3,10]}]
    assert tr.observable and tr.state=='candidate'
    assert not tr.finish()


def test_late_detector_use_suppresses_even_after_wait_window():
    tr=CashCheckTracker(CFG); sequence(tr)
    step(tr,11,[DEVICE_CASH]); step(tr,12,[DEVICE_CASH])
    assert not tr.finish() and tr.state=='device_use_observed' and tr.observable


@pytest.mark.parametrize('cash,hands', [([DEVICE_CASH],[REST]),([],[DEVICE_HAND])])
def test_single_or_ambiguous_device_observation_is_unknown(cash,hands):
    tr=CashCheckTracker(CFG); sequence(tr)
    step(tr,11,cash,hands)
    assert not tr.finish() and not tr.observable
    assert tr.state=='ambiguous_device_use'


def test_duplicate_boxes_in_one_frame_are_not_two_device_visits():
    tr=CashCheckTracker(CFG); sequence(tr)
    step(tr,11,[DEVICE_CASH,DEVICE_CASH])
    assert tr.device_hits==1 and not tr.finish()


@pytest.mark.parametrize('missing',['feed','output','cash','device','machine','hands'])
def test_missing_required_stage_does_not_become_violation(missing):
    tr=CashCheckTracker(CFG)
    for t in range(12):
        hands=[FEED] if t==0 and missing!='feed' else [TAKE] if t==3 and missing!='output' else [REST]
        if t>3 and missing=='hands': hands=[]
        gear=[d for d in [MACHINE,DEVICE] if d['label']!={'machine':'cash_counter','device':'cash_detector'}.get(missing)]
        step(tr,t,[CASH] if t>=4 and missing!='cash' else [],hands,gear)
    assert not tr.finish() and not tr.observable


@pytest.mark.parametrize('kind',['gap','degraded','front','shift','second_cycle','clipped_cash'])
def test_discontinuity_wrong_layout_and_obscuration_do_not_support_absence(kind):
    tr=CashCheckTracker(CFG); sequence(tr,6)
    for t in range(6,13):
        cash=[CASH]; hands=[REST]; gear=None; kw={}
        if kind=='gap': t+=5
        if kind=='degraded': kw['degraded']=True
        if kind=='front': kw['front_operator']=True
        if kind=='shift': gear=[{**MACHINE,'box':[250,333,320,437]},DEVICE]
        if kind=='second_cycle':
            hands=[FEED]; cash=[{**CASH,'box':[225,340,245,355]}]
        if kind=='clipped_cash': cash=[{**CASH,'box':[83,400,105,420]}]
        step(tr,t,cash,hands,gear,**kw)
    assert not tr.finish() and not tr.observable


def test_short_tail_not_a_missing_check():
    tr=CashCheckTracker(CFG); sequence(tr,7)
    assert not tr.finish() and not tr.observable


def test_large_person_mislabelled_as_hand_is_filtered():
    assert not small_objects([{**PERSON,'label':'hand'}],'hand',464,848,CFG['cash_check_hands'],.28)


def test_raised_hand_without_notes_is_not_a_second_machine_cycle():
    tr=CashCheckTracker(CFG); sequence(tr)
    step(tr,11,[CASH],[FEED])
    assert tr.finish() and not tr.invalid


def test_second_person_makes_sequence_ambiguous():
    tr=CashCheckTracker(CFG); sequence(tr)
    tr.update(11,[PERSON,{**PERSON,'box':[280,420,380,650]}],
              [MACHINE,DEVICE,CASH],[REST],464,848)
    assert not tr.finish() and not tr.observable


def test_last_original_cash_frame_is_retained_when_cash_disappears_at_eof():
    tr=CashCheckTracker(CFG); sequence(tr)
    step(tr,11,[],[REST])
    assert tr.finish()[0]['evidence_times']==[0,3,10]


class SequenceDetector:
    def detect(self,image,labels):
        t=image.getpixel((0,0))[0]-100
        if labels==['person']: return [PERSON]
        if labels==EQUIPMENT_LABELS:
            zone=CFG['cash_check_search']; rows=[MACHINE,DEVICE]+([CASH] if t>=4 else [])
        elif labels==['hand']:
            zone=CFG['cash_check_hands']; rows=[FEED if t==0 else TAKE if t==3 else REST]
        else: return []
        dx,dy=int(zone[0]*464),int(zone[1]*848)
        return [{**r,'box':[v-(dx if i%2==0 else dy) for i,v in enumerate(r['box'])]} for r in rows]
    def memory_mb(self): return None


def test_pipeline_retains_original_evidence_across_long_video(monkeypatch):
    import forte.pipeline as module
    monkeypatch.setattr(module,'sampled_frames',lambda *a:iter(
        (t,Image.new('RGB',(464,848),(100+t,100,100))) for t in range(45)))
    result=module.Pipeline(SequenceDetector()).analyze('neutral-name.mov')
    events=[e for e in result['violations'] if e['rule_id']=='no_count_check']
    assert len(events)==1
    assert [f['timestamp_sec'] for f in events[0]['evidence_frames']]==[0,3,44]
    assert events[0]['classification']=='visual_candidate' and events[0]['review_required']
    assert 'Ручной полистный пересчёт автоматически не оценивается' in events[0]['description']
    assert next(c for c in result['rule_checks'] if c['rule_id']=='no_count_check')['status']=='candidate'
