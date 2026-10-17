import pytest
from forte.desk_clear import DeskClearTracker, desk_materials


def item(label='notebook',box=None,score=.8):
    return {'label':label,'score':score,'box':box or [180,380,232,412]}


def prepared():
    tr=DeskClearTracker()
    for t in range(3):
        assert not tr.update(t,True,False,False,[item()])
    return tr


def test_left_notebook_requires_persistent_departure_and_deduplicates():
    tr=prepared()
    events=[e for t in range(3,9) for e in tr.update(t,False,False,t==3,[item()])]
    assert len(events)==1
    assert events[0]['timecode_sec']==3 and events[0]['confirmed_at']==6
    assert events[0]['detected_items']==['notebook']


@pytest.mark.parametrize('staff,visitor,exit,items',[
    (True,False,True,[item()]),(False,True,True,[item()]),
    (False,False,False,[item()]),(False,False,True,[]),
])
def test_working_visitor_no_exit_or_cleared_desk_is_not_violation(staff,visitor,exit,items):
    tr=prepared()
    assert not [e for t in range(3,9) for e in tr.update(t,staff,visitor,exit,items)]


def test_missing_frames_and_occlusion_reset_evidence():
    for gap in [False,True]:
        tr=prepared()
        tr.update(3,False,False,True,[item()])
        tr.update(10 if gap else 4,False,False,True,[],degraded=not gap)
        assert not [e for t in range(11,17) for e in tr.update(t,False,False,True,[item()])]


def test_late_object_or_changed_object_cannot_inherit_staff_contact():
    tr=prepared()
    different=item(box=[300,380,350,412])
    assert not [e for t in range(3,9) for e in tr.update(t,False,False,True,[different])]


def test_duplicate_rows_do_not_count_as_distinct_frames():
    tr=DeskClearTracker()
    tr.update(0,True,False,False,[item(),item(),item()])
    assert len(tr.tracks)==1 and tr.tracks[0]['hits']==1
    assert not tr.update(1,False,False,True,[item()]*5)


def test_select_materials_rejects_laptop_counting_machine_and_empty_container():
    zone=[.23,.40,.67,.56]
    notebook=item()
    container=item('container',[223,397,235,417],.35)
    coin=item('coins',[222,395,245,418],.27)
    machine=item('container',[151,404,207,446],.9)
    assert desk_materials([notebook],464,848,zone)==[notebook]
    found=desk_materials([container,machine],464,848,zone)
    assert len(found)==1 and not found[0]['coin_evidence']
    found=desk_materials([container,coin,machine],464,848,zone)
    assert len(found)==1 and found[0]['coin_evidence']
    assert desk_materials([notebook,item('laptop')],464,848,zone)==[]
    assert desk_materials([item(box=[106,366,142,429])],464,848,zone)==[]


def test_notebook_and_coin_container_are_reported_separately_in_one_event():
    tr=DeskClearTracker()
    objects=[item(),{**item('small_container',[223,397,235,417]),'coin_evidence':True}]
    for t in range(3): tr.update(t,True,False,False,objects)
    events=[e for t in range(3,8) for e in tr.update(t,False,False,True,objects)]
    assert len(events)==1
    assert events[0]['detected_items']==['notebook','possible_coin_container']


def test_container_requires_repeated_coin_evidence_but_not_every_frame():
    for coin_hits in [0,1,3]:
        tr=DeskClearTracker()
        container=item('small_container',[223,397,235,417])
        for t in range(3):
            tr.update(t,True,False,False,[{**container,'coin_evidence':t<coin_hits}])
        events=[e for t in range(3,8) for e in tr.update(t,False,False,True,[container])]
        assert bool(events)==(coin_hits==3)
