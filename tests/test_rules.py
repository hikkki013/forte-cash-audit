from forte.rules import Observation, RuleEngine

CFG = {"sample_seconds":1,"absence_seconds":3,"safe_seconds":5,
       "enabled_rules":["cash_unattended","prev_client_cash","safe_left_open"]}
BOX = [10,10,20,20]

def test_cash_absence_persistence_and_dedup():
    e = RuleEngine(CFG)
    assert not e.update(Observation(0,True,False,True))
    found = []
    for t in range(1,9):
        found += e.update(Observation(t,False,False,True))
    assert len(found)==1 and found[0]["timecode_sec"]==1

def test_empty_table_and_never_seen_cashier_not_violation():
    for cash in [False,True]:
        e=RuleEngine(CFG)
        assert not [x for t in range(10) for x in e.update(Observation(t,False,False,cash))]

def test_missing_detections_reset_window():
    e=RuleEngine(CFG)
    e.update(Observation(0,True,False,True))
    e.update(Observation(1,False,False,True))
    e.update(Observation(2,False,False,False))
    assert not e.update(Observation(3,False,False,True))
    assert not e.update(Observation(4,False,False,True))

def test_gap_does_not_count_as_persistence():
    e=RuleEngine(CFG)
    e.update(Observation(0,True,False,True))
    e.update(Observation(1,False,False,True))
    assert not e.update(Observation(20,False,False,True))

def test_safe_unknown_and_person_near_safe():
    for state,near in [(None,False),(True,True),(False,False)]:
        e=RuleEngine(CFG)
        assert not [x for t in range(9) for x in e.update(Observation(t,True,False,False,state,near))]
    e=RuleEngine(CFG)
    found=[x for t in range(9) for x in e.update(Observation(t,True,False,False,True,False))]
    assert len(found)==1 and found[0]["rule_id"]=="safe_left_open"

def test_previous_client_requires_leave_then_return_and_stationary_cash():
    e=RuleEngine(CFG)
    found=[]
    for t,client in enumerate([True,True,False,False,False,True,True,True]):
        found += e.update(Observation(t,True,client,True,cash_box=BOX))
    assert [x["rule_id"] for x in found]==["prev_client_cash"]

def test_money_removed_breaks_previous_client_rule():
    e=RuleEngine(CFG)
    found=[]
    for t,client in enumerate([True,True,False,False,False,True,True]):
        cash=t!=4
        found += e.update(Observation(t,True,client,cash,cash_box=BOX if cash else None))
    assert not found

def test_disabled_rules_never_emit():
    e=RuleEngine({**CFG,"enabled_rules":[]})
    e.update(Observation(0,True,False,True))
    assert not [x for t in range(1,10) for x in e.update(Observation(t,False,False,True,True,False))]

def test_exit_gate_avoids_cashier_working_at_safe():
    e=RuleEngine({**CFG,'require_exit':True})
    e.update(Observation(0,True,False,True))
    assert not [x for t in range(1,8) for x in e.update(Observation(t,False,False,True))]
    found=e.update(Observation(8,False,False,True,at_exit=True))
    assert len(found)==1 and found[0]['confirmed_at']==8
