import json
from pathlib import Path
import pytest
from PIL import Image
import numpy as np
from forte.scene_events import SceneEvents,distinct_people
from forte.safe_state import calibrated_safe_state

CFG=json.loads(Path('config/scene.json').read_text(encoding='utf-8'))
def person(box,score=.9): return {'label':'person','box':box,'score':score}
FRONT=person([300,480,600,780])
BACK=person([250,360,550,540])
VISITOR=person([200,260,400,490])
SECOND=person([60,180,200,480])
def obj(label='bag',dx=0): return {'label':label,'box':[300+dx,440,380+dx,480],'score':.8}


def step(tr,t,people,objects,exit=False):
    staff,visitors,observed_exit=tr.roles(t,people,1000,1000)
    return tr.update(t,staff,visitors,exit or observed_exit,objects)


def front_scene():
    tr=SceneEvents(CFG)
    step(tr,0,[FRONT],[]); step(tr,1,[FRONT],[])
    assert tr.front
    return tr


def test_bag_employee_departure_not_contents():
    tr=SceneEvents(CFG)
    for t in range(4): assert not step(tr,t,[BACK],[obj()])
    events=[e for t in range(4,10) for e in step(tr,t,[],[obj()],exit=t==4)]
    assert [(e['rule_id'],e['timecode_sec']) for e in events]==[('bag_left_by_employee',4)]


def test_bag_visitor_departure_and_background_exclusion():
    tr=front_scene()
    for t in range(2,6): step(tr,t,[FRONT,VISITOR],[obj()])
    events=[e for t in range(6,10) for e in step(tr,t,[FRONT],[obj()],exit=t==6)]
    assert [e['rule_id'] for e in events]==['bag_left_by_visitor']
    tr=front_scene()
    for t in range(2,5): step(tr,t,[FRONT],[obj()])
    for t in range(5,8): step(tr,t,[FRONT,VISITOR],[obj()])
    assert not [e for t in range(8,12) for e in step(tr,t,[FRONT],[obj()],exit=t==8)]


def test_no_bag_departure_without_exit_or_when_bag_removed():
    for keep_bag,exit_seen in [(True,False),(False,True)]:
        tr=SceneEvents(CFG)
        for t in range(4): step(tr,t,[BACK],[obj()])
        assert not [e for t in range(4,10) for e in step(tr,t,[],[obj()] if keep_bag else [],exit=exit_seen)]


def test_static_background_bag_without_employee_contact_is_not_abandonment():
    tr=SceneEvents(CFG)
    background=obj(dx=350)
    for t in range(4): step(tr,t,[BACK],[background])
    assert not [e for t in range(4,10) for e in step(tr,t,[],[background],exit=True)]


def test_multiple_visitors_ignore_duplicate_boxes_and_reflections():
    tr=front_scene()
    events=[e for t in range(2,7) for e in step(tr,t,[FRONT,VISITOR,SECOND],[])]
    assert [(e['rule_id'],e['timecode_sec']) for e in events]==[('several_clients',2)]
    tr=front_scene()
    reflection=person([20,100,150,300])
    assert not [e for t in range(2,7) for e in step(tr,t,[FRONT,VISITOR,VISITOR,reflection],[])]
    assert len(distinct_people([VISITOR,VISITOR]))==1


def test_previous_cash_tracks_short_motion_and_deduplicates():
    tr=front_scene()
    for t in range(2,6): step(tr,t,[FRONT,VISITOR],[obj('cash')])
    for t in range(6,9): step(tr,t,[FRONT],[obj('cash')],exit=t==6)
    events=[e for t in range(9,15) for e in step(tr,t,[FRONT,VISITOR],[obj('cash',50)])]
    assert [e['rule_id'] for e in events]==['prev_client_cash']
    assert events[0]['timecode_sec']==9


def test_removed_cash_cannot_be_resurrected_at_same_coordinates():
    tr=front_scene()
    for t in range(2,6): step(tr,t,[FRONT,VISITOR],[obj('cash')])
    for t in range(6,9): step(tr,t,[FRONT],[obj('cash')],exit=t==6)
    for t in range(9,13): step(tr,t,[FRONT],[])
    assert not [e for t in range(13,18) for e in step(tr,t,[FRONT,VISITOR],[obj('cash')])]


def test_decode_gap_clears_layout_and_temporal_state():
    tr=front_scene()
    for t in range(2,5): step(tr,t,[FRONT,VISITOR],[obj()])
    assert not step(tr,20,[FRONT],[obj()],exit=True)
    assert not tr.front


def test_duplicate_objects_are_not_multiple_frames():
    tr=SceneEvents(CFG)
    step(tr,0,[BACK],[obj(),obj(),obj()])
    assert len(tr.tracks)==1 and tr.tracks[0]['hits']==1


def test_safe_classifier_rejects_unknown_and_missing_calibration():
    cal=json.loads(Path('config/safe_prototypes.json').read_text())
    assert calibrated_safe_state(Image.new('RGB',(464,848),'black'),cal)['open'] is None
    assert calibrated_safe_state(Image.new('RGB',(100,180),'gray'),cal)['open'] is None
    assert calibrated_safe_state(Image.new('RGB',(464,848)),None)['open'] is None


@pytest.mark.parametrize('state',[False,True])
def test_safe_classifier_recognizes_own_prototype_not_accuracy_claim(state):
    cal=json.loads(Path('config/safe_prototypes.json').read_text())
    row=next(r for r in cal['prototypes'] if r['open']==state)
    patch=Image.fromarray(np.asarray(row['values'],dtype=np.uint8).reshape(18,12)).convert('RGB')
    im=Image.new('RGB',(464,848))
    bounds=tuple(int(v*s) for v,s in zip(cal['zone'],[464,848,464,848]))
    im.paste(patch.resize((bounds[2]-bounds[0],bounds[3]-bounds[1])),bounds[:2])
    assert calibrated_safe_state(im,cal)['open']==state
