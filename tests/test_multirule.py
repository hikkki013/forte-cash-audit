import json
from pathlib import Path
import pytest
from PIL import Image
from forte.rules import Observation, RuleEngine
from forte.coverage import rule_checks
from forte.pipeline import Pipeline, state_in_zone, frame_quality

CATALOG = json.loads(Path('config/rules.json').read_text(encoding='utf-8'))
CFG = json.loads(Path('config/scene.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('rule,field,duration', [
    ('phone_with_camera','phone_at_cashier',3),
    ('personal_items','clothing_on_desk',5),
    ('food_at_workplace','food_at_cashier',5),
    ('door_open','door_open',5),
    ('camera_obstructed','camera_degraded',2),
])
def test_added_rules_persist_reset_and_deduplicate(rule,field,duration):
    e = RuleEngine({**CFG,'enabled_rules':[rule]})
    found = []
    for t in range(duration+4):
        found += e.update(Observation(t,True,False,False,**{field:True}))
    assert len(found)==1 and found[0]['rule_id']==rule
    assert found[0]['timecode_sec']==0 and found[0]['confirmed_at']==duration
    e.update(Observation(duration+4,True,False,False))
    assert not e.update(Observation(duration+5,True,False,False,**{field:True}))


def test_service_departure_requires_prior_cashier_client_and_exit():
    e = RuleEngine({**CFG,'enabled_rules':['left_during_service']})
    e.update(Observation(0,True,True,False))
    assert not [x for t in range(1,8) for x in e.update(Observation(t,False,True,False))]
    result = [x for t in range(8,15) for x in e.update(Observation(t,False,True,False,at_exit=True))]
    assert len(result)==1
    assert result[0]['rule_id']=='left_during_service'


def test_phone_on_client_or_no_cashier_is_not_cashier_phone():
    e=RuleEngine({**CFG,'enabled_rules':['phone_with_camera']})
    assert not [x for t in range(8) for x in e.update(Observation(t,False,True,False,phone_at_cashier=True))]


def test_unknown_state_and_missing_frames_never_mean_closed_or_persistence():
    assert state_in_zone([], 'safe',[0,0,1,1],100,100) is None
    ambiguous=[{'label':label,'score':.6,'box':[10,10,20,20]} for label in ['safe_open','safe_closed']]
    assert state_in_zone(ambiguous,'safe',[0,0,1,1],100,100) is None
    e=RuleEngine({**CFG,'enabled_rules':['door_open']})
    e.update(Observation(0,True,False,False,door_open=True))
    assert not e.update(Observation(10,True,False,False,door_open=True))


def test_every_source_rule_has_a_status_and_manual_is_not_passed():
    assert len(CATALOG)==33 and len(CFG['enabled_rules'])==20
    checks=rule_checks(CATALOG,CFG['enabled_rules'],[],{},10)
    assert len(checks)==33 and len({c['rule_id'] for c in checks})==33
    assert all(c['status'] in {'not_implemented','insufficient_evidence'} for c in checks)
    assert next(c for c in checks if c['rule_id']=='pc_not_shutdown')['status']=='insufficient_evidence'
    assert next(c for c in checks if c['rule_id']=='no_client_id')['status']=='insufficient_evidence'
    assert next(c for c in checks if c['rule_id']=='cash_foreign_object')['status']=='not_implemented'
    short=rule_checks(CATALOG,CFG['enabled_rules'],[],dict.fromkeys(CATALOG,3),3)
    assert next(c for c in short if c['rule_id']=='food_at_workplace')['status']=='insufficient_evidence'


class FakeDetector:
    def detect(self,image,labels):
        if labels==['person']:
            return [{'label':'person','score':.9,'box':[190,350,325,600]}]
        if 'phone' in labels:
            return [{'label':label,'score':.9,'box':[130,80,155,105]} for label in ['phone','food']]
        return []
    def memory_mb(self):
        return None


def test_pipeline_multiple_events_and_all_rule_statuses(monkeypatch):
    import forte.pipeline as module
    monkeypatch.setattr(module,'sampled_frames',lambda *a: iter((t,Image.new('RGB',(548,1000),'gray')) for t in range(8)))
    result=Pipeline(FakeDetector()).analyze('unused-test-only.mp4')
    assert {e['rule_id'] for e in result['violations']}=={'phone_with_camera','food_at_workplace'}
    assert result['verdict']=='violation' and len(result['rule_checks'])==33
    assert all(e['evidence_frames'] and e['review_required'] for e in result['violations'])
    import base64
    import io
    for event in result['violations']:
        assert event['type'] == CATALOG[event['rule_id']]['event_title']
        assert event['description'] and event['timecode_sec'] >= 0
        assert event['rule_title']==CATALOG[event['rule_id']]['title']
        assert event['requirement'] and event['applicability'] and event['limits']
        assert event['source_verified'] is False
        assert event['source_text_verified']==bool(CATALOG[event['rule_id']].get('source_text_verified'))
        assert 1 <= len(event['evidence_frames']) <= 3
        for frame in event['evidence_frames']:
            assert frame['timestamp_sec'] >= 0
            assert Image.open(io.BytesIO(base64.b64decode(frame['image_base64']))).format == 'JPEG'


def test_black_video_reports_camera_candidate_without_invented_people(monkeypatch):
    import forte.pipeline as module
    monkeypatch.setattr(module,'sampled_frames',lambda *a: iter((t,Image.new('RGB',(548,1000),'black')) for t in range(4)))
    result=Pipeline(FakeDetector()).analyze('unused-test-only.mp4')
    assert [e['rule_id'] for e in result['violations']]==['camera_obstructed']
    assert all(c['status']!='not_detected' for c in result['rule_checks'])


def test_no_event_returns_spec_verdict_with_separate_partial_coverage(monkeypatch):
    import forte.pipeline as module
    monkeypatch.setattr(module,'sampled_frames',lambda *a: iter([(0,Image.new('RGB',(548,1000),'gray'))]))
    result=Pipeline(FakeDetector()).analyze('unused-test-only.mp4')
    assert result['verdict']=='no_violation' and result['violations']==[]
    assert result['coverage_status']=='partial'
    assert any(c['status']=='not_implemented' for c in result['rule_checks'])


def test_frame_quality_does_not_call_normal_gray_obstruction():
    assert frame_quality(Image.new('RGB',(20,20),'black'))
    assert not frame_quality(Image.new('RGB',(20,20),'gray'))
