import json
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
from forte.screen import screen_state
from forte.rules import Observation, RuleEngine

CFG=json.loads(Path('config/scene.json').read_text(encoding='utf-8'))

def obs(t, cashier=False, active=True, exit=False):
    return Observation(t,cashier,False,False,at_exit=exit,screen_active=active)

def engine():
    e=RuleEngine({**CFG,'enabled_rules':['pc_not_shutdown']})
    e.update(obs(0,True)); e.update(obs(1,True))
    return e

@pytest.mark.parametrize('value,expected',[(180,True),(25,False),(90,None)])
def test_visible_screen_state(value,expected):
    image=Image.new('RGB',(464,848),'white')
    ImageDraw.Draw(image).rectangle((270,320,315,375),fill=(value,)*3)
    detection={'label':'screen','score':.8,'box':[270,320,315,375]}
    assert screen_state(image,[detection])['active'] is expected

def test_missing_small_or_uncertain_screen_is_unknown():
    image=Image.new('RGB',(464,848),'white')
    for rows in [[],[{'label':'screen','score':.3,'box':[270,320,315,375]}],
                 [{'label':'screen','score':.9,'box':[270,320,275,325]}]]:
        assert screen_state(image,rows)['active'] is None

def test_departure_emits_once_with_onset_and_confirmation():
    e=engine()
    events=[event for t in range(2,12) for event in e.update(obs(t,exit=t==4))]
    assert len(events)==1
    assert events[0]['rule_id']=='pc_not_shutdown'
    assert events[0]['timecode_sec']==2 and events[0]['confirmed_at']==7

@pytest.mark.parametrize('active',[False,None])
def test_dark_or_unreadable_screen_cannot_fire(active):
    e=engine()
    assert not [event for t in range(2,12) for event in e.update(obs(t,active=active,exit=True))]

def test_no_exit_or_initial_empty_workplace_cannot_fire():
    e=engine()
    assert not [event for t in range(2,12) for event in e.update(obs(t))]
    e=RuleEngine(CFG)
    assert not [event for t in range(10) for event in e.update(obs(t,exit=True))]

def test_short_absence_return_and_decode_gap_do_not_fire():
    e=engine()
    for t in range(2,6): assert not e.update(obs(t,exit=True))
    assert not e.update(obs(6,True))
    assert not e.update(obs(7,True))
    assert not e.update(obs(8,exit=True))
    assert not e.update(obs(20,exit=True))
    assert not [event for t in range(21,30) for event in e.update(obs(t,exit=True))]

def test_unknown_observation_resets_active_duration():
    e=engine()
    for t in range(2,6): assert not e.update(obs(t,exit=True))
    assert not e.update(obs(6,active=None))
    for t in range(7,12): assert not e.update(obs(t))
    assert e.update(obs(12))[0]['timecode_sec']==7
