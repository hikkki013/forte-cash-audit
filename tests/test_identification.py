"""Synthetic sequence tests: the detector must not infer identity from absence."""
import json
from pathlib import Path
import pytest
from PIL import Image
from forte.identification import IdentificationTracker, small_items, DOCUMENT_LABELS
from forte.pipeline import Pipeline

CFG = json.loads(Path('config/scene.json').read_text(encoding='utf-8'))
STAFF = {'label':'person','score':.8,'box':[350,450,600,730]}
CLIENT = {'label':'person','score':.8,'box':[240,200,450,450]}
INCOMING = {'label':'cash','score':.6,'box':[300,445,320,455]}
HAND = {'label':'cash','score':.6,'box':[400,490,430,510]}
CARD = {'label':'id_card','score':.5,'box':[300,530,320,540]}


def step(tr,t,cash=(),docs=(),people=None,**kw):
    return tr.update(t,[STAFF,CLIENT] if people is None else people,list(cash),list(docs),1000,1000,**kw)


def ready():
    tr=IdentificationTracker(CFG)
    step(tr,0,people=[STAFF]); step(tr,1,people=[STAFF])
    return tr


def received(tr,docs=()):
    assert not step(tr,2,[INCOMING],docs)
    assert not step(tr,3,[HAND],docs)
    assert not step(tr,4,[HAND])
    assert not step(tr,5)
    assert not step(tr,6)


def test_candidate_only_at_end_of_fragment_with_real_transfer_and_dedup():
    tr=ready(); received(tr)
    result=tr.finish()
    assert result==[{'rule_id':'no_client_id','timecode_sec':3,'confirmed_at':6,
                    'duration_sec':3,'evidence_times':[2,3,4]}]
    assert tr.observable and tr.state=='candidate'
    assert not tr.finish()


def test_document_on_separate_frames_suppresses_candidate():
    tr=ready(); received(tr,[CARD])
    assert not tr.finish() and tr.observable and tr.state=='document_observed'


def test_document_later_in_fragment_also_suppresses_conservative_candidate():
    tr=ready(); received(tr)
    step(tr,7,docs=[CARD]); step(tr,8,docs=[CARD])
    assert not tr.finish() and tr.state=='document_observed'


@pytest.mark.parametrize('label',['phone','passport'])
def test_possible_digital_or_ambiguous_document_is_unknown(label):
    tr=ready(); received(tr,[{**CARD,'label':label}])
    assert not tr.finish() and not tr.observable and tr.state=='ambiguous_document'


def test_duplicate_document_boxes_on_one_frame_are_not_two_observations():
    tr=ready(); step(tr,2,[INCOMING],[CARD,CARD]); step(tr,3,[HAND]); step(tr,4,[HAND])
    step(tr,5); step(tr,6)
    assert not tr.finish() and not tr.observable


def test_video_starting_mid_service_is_unknown():
    tr=IdentificationTracker(CFG); received(tr)
    assert not tr.finish() and not tr.observable


@pytest.mark.parametrize('mode',['timestamp_gap','missing_client','black_frame','missing_staff','extra_client'])
def test_incomplete_observation_never_becomes_violation(mode):
    tr=ready(); step(tr,2,[INCOMING]); step(tr,3,[HAND])
    if mode=='timestamp_gap': step(tr,10,[HAND])
    elif mode=='missing_client': step(tr,4,people=[STAFF])
    elif mode=='black_frame': step(tr,4,degraded=True)
    elif mode=='missing_staff': step(tr,4,people=[CLIENT])
    else: step(tr,4,people=[STAFF,CLIENT,{'score':.8,'box':[650,200,800,460]}])
    for t in range(11,15) if mode=='timestamp_gap' else range(5,9): step(tr,t,[HAND])
    assert not tr.finish() and not tr.observable


def test_weak_person_needs_overlap_with_previously_observed_person():
    tr=ready(); received(tr)
    step(tr,7,people=[STAFF,{**CLIENT,'score':.36}])
    assert tr.finish()  # A real overlapping box, not invented presence.
    tr=ready(); step(tr,2,people=[STAFF,{**CLIENT,'score':.36}])
    assert tr.visit is None


def test_no_cash_or_no_incoming_never_means_failed_identification():
    for cash in ([],[HAND]):
        tr=ready()
        for t in range(2,10): step(tr,t,cash)
        assert not tr.finish() and not tr.observable


def test_cash_already_present_before_visit_cannot_establish_clear_start():
    tr=IdentificationTracker(CFG)
    for t in (0,1): step(tr,t,[INCOMING],people=[STAFF])
    received(tr)
    assert not tr.finish()


def test_short_video_does_not_complete_pending_candidate():
    tr=ready(); step(tr,2,[INCOMING]); step(tr,3,[HAND]); step(tr,4,[HAND])
    assert not tr.finish() and not tr.observable


def test_old_incoming_object_cannot_link_to_unrelated_cash_later():
    tr=ready(); step(tr,2,[INCOMING])
    for t in range(3,10): step(tr,t)
    for t in range(10,15): step(tr,t,[HAND])
    assert not tr.finish()


def test_visits_are_separate_and_document_does_not_leak_to_next_client():
    tr=ready(); received(tr,[CARD])
    step(tr,7,people=[STAFF]); assert not step(tr,8,people=[STAFF])
    for t in (9,10): step(tr,t,people=[STAFF])
    step(tr,11,[INCOMING]); step(tr,12,[HAND]); step(tr,13,[HAND]); step(tr,14); step(tr,15)
    result=tr.finish()
    assert len(result)==1 and result[0]['timecode_sec']==12


@pytest.mark.parametrize('bad',[
    {**INCOMING,'score':.2},
    {**INCOMING,'box':[200,440,520,590]},
    {**INCOMING,'label':'paper'},
])
def test_weak_clipped_or_wrong_class_detections_rejected(bad):
    assert not small_items([bad],1000,1000,[.20,.44,.52,.59],{'cash'},.35)


class SequenceDetector:
    """Synthetic boxes in the real crop coordinate system, no model required."""
    def __init__(self,document=False): self.document=document
    def detect(self,image,labels):
        t=image.getpixel((0,0))[0]-100
        def scale(row,zone=(0,0,1,1)):
            b=row['box']
            return {**row,'box':[(b[0]/1000-zone[0])*548,(b[1]/1000-zone[1])*1000,
                                 (b[2]/1000-zone[0])*548,(b[3]/1000-zone[1])*1000]}
        if labels==['person']:
            return [scale(STAFF)]+([scale(CLIENT)] if t>=2 else [])
        if labels==['cash']:
            rows=[INCOMING] if t==2 else [HAND] if t in (3,4) else []
            return [scale(r,(int(.20*548)/548,.44,1,1)) for r in rows]
        if labels==DOCUMENT_LABELS and self.document and t in (2,3):
            return [scale(CARD,(int(.18*548)/548,.36,1,1))]
        return []
    def memory_mb(self): return None


@pytest.mark.parametrize('document',[False,True])
def test_pipeline_end_of_file_candidate_coverage_and_exact_evidence(monkeypatch,document):
    import forte.pipeline as module
    # Long visit deliberately exceeds the ordinary 32-frame evidence ring.
    monkeypatch.setattr(module,'sampled_frames',lambda *a:iter(
        (t,Image.new('RGB',(548,1000),(100+t,100,100))) for t in range(45)))
    result=Pipeline(SequenceDetector(document)).analyze('arbitrary-renamed-file.mov')
    events=[e for e in result['violations'] if e['rule_id']=='no_client_id']
    check=next(c for c in result['rule_checks'] if c['rule_id']=='no_client_id')
    if document:
        assert not events and check['status']=='not_detected'
    else:
        assert len(events)==1 and check['status']=='candidate'
        assert [f['timestamp_sec'] for f in events[0]['evidence_frames']]==[2,3,4]
        assert events[0]['review_required'] and events[0]['classification']=='visual_candidate'
        assert events[0]['requirement'] and events[0]['source'] and events[0]['paragraph']
        assert not events[0]['source_text_verified']
