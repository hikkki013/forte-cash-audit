import pytest
from forte.cash_return import CashReturnTracker

NEAR={'score':.8,'box':[350,450,600,730]}
FAR={'score':.8,'box':[240,200,450,450]}
CLIENT={'label':'cash','score':.6,'box':[300,445,320,455]}
HAND={'label':'cash','score':.6,'box':[400,490,430,510]}
LEFT={'label':'cash','score':.6,'box':[300,530,320,540]}

def ready():
    tracker=CashReturnTracker({'sample_seconds':1})
    assert not tracker.prepare(0,[NEAR],1000,1000)
    assert not tracker.prepare(1,[NEAR],1000,1000)
    return tracker

def step(tracker,t,boxes,people=None):
    if tracker.prepare(t,[NEAR,FAR] if people is None else people,1000,1000):
        return tracker.update(t,boxes)
    return []

def handled(tracker):
    assert not step(tracker,2,[CLIENT])
    for t in [3,4,5]: assert not step(tracker,t,[HAND,LEFT])

def test_complete_visual_sequence_onset_evidence_and_dedup():
    tr=ready(); handled(tr)
    assert not step(tr,6,[LEFT,CLIENT])
    result=step(tr,7,[LEFT,CLIENT])
    assert result[0]['timecode_sec']==6 and result[0]['confirmed_at']==7
    assert result[0]['evidence_times']==[3,6,7]
    assert not step(tr,8,[LEFT,CLIENT])

def test_no_retained_cash_no_candidate():
    tr=ready(); handled(tr)
    assert not step(tr,6,[CLIENT])
    assert not step(tr,7,[CLIENT])

def test_no_return_no_candidate():
    tr=ready(); handled(tr)
    for t in range(6,12): assert not step(tr,t,[LEFT])

def test_missing_incoming_transfer_no_candidate():
    tr=ready()
    for t in range(2,8): assert not step(tr,t,[HAND,LEFT])
    for t in range(8,11): assert not step(tr,t,[LEFT,CLIENT])

def test_both_people_at_start_does_not_guess_operator():
    tr=CashReturnTracker({'sample_seconds':1})
    for t in range(10): assert not step(tr,t,[LEFT,HAND,CLIENT])

def test_missing_frame_gap_clears_sequence():
    tr=ready(); handled(tr)
    assert not step(tr,15,[LEFT,CLIENT])
    assert not step(tr,16,[LEFT,CLIENT])

def test_client_departure_clears_sequence():
    tr=ready(); handled(tr)
    for t in range(6,10): assert not step(tr,t,[],people=[NEAR])
    assert not step(tr,10,[LEFT,CLIENT])
    assert not step(tr,11,[LEFT,CLIENT])

@pytest.mark.parametrize('bad',[
    {'label':'cash','score':.2,'box':[300,530,320,540]},
    {'label':'cash','score':.8,'box':[200,440,520,590]},
    {'label':'cash','score':.8,'box':[200,500,220,550]},
    {'label':'paper','score':.9,'box':[300,530,320,540]},
])
def test_uncertain_clipped_or_non_cash_residual_cannot_fire(bad):
    tr=ready(); step(tr,2,[CLIENT])
    for t in [3,4,5]: assert not step(tr,t,[HAND,bad])
    for t in [6,7]: assert not step(tr,t,[CLIENT,bad])
