import json
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
from forte.access_checks import RearEntryTracker, ClientDepartureTracker, door_state

CFG=json.loads(Path('config/scene.json').read_text(encoding='utf-8'))
WORKER={'label':'person','score':.8,'box':[280,330,500,600]}
ENTRANT={'label':'person','score':.8,'box':[100,200,260,500]}
STAFF={**WORKER,'box':[350,500,600,750]}
CLIENT={**WORKER,'box':[300,280,450,480]}
CASH={'label':'cash','score':.6,'box':[380,490,410,510]}
MACHINE={'label':'cash_counter','score':.6,'box':[550,350,700,500]}
HAND={'label':'hand','score':.6,'box':[580,350,620,380]}


def test_rear_entry_requires_prior_single_worker_and_persistence():
    tr=RearEntryTracker()
    assert not tr.update(0,[WORKER],1000,1000)
    assert not tr.update(1,[WORKER],1000,1000,door_open=True)
    assert not tr.update(2,[WORKER,ENTRANT],1000,1000)
    ev=tr.update(3,[WORKER,ENTRANT],1000,1000)
    assert len(ev)==1 and ev[0]['rule_id']=='outsider_in_cashroom' and ev[0]['timecode_sec']==2
    assert not tr.update(4,[WORKER,ENTRANT],1000,1000)


@pytest.mark.parametrize('kind',['front','degraded','no_baseline','duplicate','reflection','gap'])
def test_entry_does_not_invent_intruder(kind):
    tr=RearEntryTracker()
    if kind!='no_baseline':
        tr.update(0,[WORKER],1000,1000); tr.update(1,[WORKER],1000,1000)
    rows=[WORKER,ENTRANT]
    if kind=='duplicate': rows=[WORKER,WORKER]
    if kind=='reflection': rows=[WORKER,{**ENTRANT,'box':[50,100,100,190]}]
    assert not [ev for t in range(2,5) for ev in tr.update(t+10 if kind=='gap' else t,rows,
                        1000,1000,front=kind=='front',degraded=kind=='degraded',door_open=True)]


@pytest.mark.parametrize('state',[False,None,'stale','closed_after_open'])
def test_second_person_without_recent_open_door_is_not_entry(state):
    tr=RearEntryTracker()
    tr.update(0,[WORKER],1000,1000,door_open=True if state in ('stale','closed_after_open') else state)
    tr.update(1,[WORKER],1000,1000)
    for t in range(2,8):
        rows=[WORKER] if state=='stale' and t<4 else [WORKER,ENTRANT]
        assert not tr.update(t,rows,1000,1000,door_open=False if state in (False,'closed_after_open') else None)


def prepare(tr,t,client=False,cash=False,exit=False,**kw):
    return tr.prepare(t,[STAFF]+([CLIENT] if client else []),[CASH] if cash else [],1000,1000,
                      True,exit,**kw)


def ready():
    tr=ClientDepartureTracker(CFG)
    for t in range(3): assert not prepare(tr,t,client=True,cash=True)
    assert not prepare(tr,3,exit=True)
    return tr


def test_departure_requires_cash_then_exit_then_repeated_machine_action():
    tr=ready()
    assert prepare(tr,4)
    assert not tr.update_action(4,[MACHINE],[HAND],1000,1000)
    assert prepare(tr,5)
    ev=tr.update_action(5,[MACHINE],[HAND],1000,1000)
    assert len(ev)==1 and ev[0]['timecode_sec']==4
    assert ev[0]['evidence_times']==[0,3,5]
    assert not tr.update_action(6,[MACHINE],[HAND],1000,1000)


@pytest.mark.parametrize('kind',['cash','exit','client_stays','degraded','gap','returning_client'])
def test_absence_of_detection_is_not_client_departure(kind):
    tr=ClientDepartureTracker(CFG)
    for t in range(3): prepare(tr,t,client=True,cash=kind!='cash')
    for t in range(3,6):
        assert not prepare(tr,t+10 if kind=='gap' else t,
                           client=kind in ('client_stays','returning_client'),
                           exit=kind!='exit',degraded=kind=='degraded')


@pytest.mark.parametrize('hands,machines',[([], [MACHINE]),([HAND],[]),([WORKER],[MACHINE])])
def test_machine_or_person_without_small_hand_is_not_action(hands,machines):
    tr=ready()
    for t in range(4,8):
        assert prepare(tr,t)
        assert not tr.update_action(t,machines,hands,1000,1000)


def calibration_fixture():
    z=[.1,.06,.29,.25]; w,h=464,848
    im=Image.new('RGB',(w,h),'gray'); box=tuple(int(v*s) for v,s in zip(z,[w,h,w,h]))
    im.paste(Image.new('RGB',(box[2]-box[0],box[3]-box[1]),'white'),box)
    c={'zone':z,'size':[2,2],'max_mae':14,'margin':4,
       'prototypes':[{'open':True,'values':[255]*4},{'open':True,'values':[254]*4},
                     {'open':False,'values':[0]*4}]}
    return im,c


def test_door_compares_best_per_class_not_two_same_class_templates():
    im,c=calibration_fixture()
    assert door_state(im,c)['open'] is True
    assert door_state(Image.new('RGB',im.size,'black'),c)['open'] is False


def test_unknown_camera_occlusion_and_low_quality_stay_unknown():
    im,c=calibration_fixture()
    assert door_state(Image.new('RGB',im.size,'gray'),c)['open'] is None
    assert door_state(im,c,degraded=True)['open'] is None
    assert door_state(im.resize((300,200)),c)['open'] is None
    assert door_state(im,c,[{**WORKER,'box':[45,50,140,220]}])['open'] is None


def test_source_and_frontend_catalog_stay_in_sync():
    r=json.loads(Path('config/rules.json').read_text(encoding='utf-8'))
    for k in ('door_open','outsider_in_cashroom','count_without_client'):
        assert r[k]['mode']=='automatic_candidate'
        assert r[k]['source_text_verified'] and not r[k]['source_current_verified']
    assert 'общий контекст' in r['outsider_in_cashroom']['paragraph']
    assert 'полномочия' in r['outsider_in_cashroom']['limits']
    assert len(CFG['enabled_rules'])==20 and len(r)==33


def test_departure_pipeline_works_without_other_cash_rules(monkeypatch):
    import forte.pipeline as module
    class Detector:
        def detect(self,image,labels):
            t=image.getpixel((0,0))[0]-100
            zone=[0,0,1,1]; rows=[]
            if labels==['person']:
                rows=[STAFF]+([CLIENT] if 2<=t<=4 else
                              [{**ENTRANT,'box':[100,180,200,400]}] if t==5 else [])
            elif labels==['cash']:
                zone=CFG['cash_continuity_search']; rows=[CASH] if 2<=t<=4 else []
            elif labels==['cash_counter']:
                zone=CFG['departure_search']; rows=[MACHINE]
            elif labels==['hand']:
                zone=CFG['departure_search']; rows=[HAND]
            return [{**r,'box':[v*(.548 if i%2==0 else 1)-int(zone[i%2]*[548,1000][i%2])
                               for i,v in enumerate(r['box'])]} for r in rows]
        def memory_mb(self): return None
    monkeypatch.setattr(module,'sampled_frames',lambda *a:iter(
        (t,Image.new('RGB',(548,1000),(100+t,100,100))) for t in range(9)))
    p=module.Pipeline(Detector());p.config['enabled_rules']=['count_without_client']
    r=p.analyze('neutral-name.mov')
    assert len(r['violations'])==1
    e=r['violations'][0]
    assert e['rule_id']=='count_without_client' and e['timecode_sec']==6
    assert [f['timestamp_sec'] for f in e['evidence_frames']]==[2,5,7]


def test_entry_pipeline_works_with_door_rule_disabled(monkeypatch):
    import forte.pipeline as module
    class Detector:
        def detect(self,image,labels):
            if labels!=['person']: return []
            return [WORKER]+([ENTRANT] if image.getpixel((0,0))[0]>=102 else [])
        def memory_mb(self): return None
    monkeypatch.setattr(module,'sampled_frames',lambda *a:iter(
        (t,Image.new('RGB',(1000,1000),(100+t,100,100))) for t in range(4)))
    monkeypatch.setattr(module,'door_state',lambda *a: {'open':True})
    p=module.Pipeline(Detector());p.config['enabled_rules']=['outsider_in_cashroom']
    p.config['expected_aspect']=1
    r=p.analyze('neutral-name.mov')
    assert [(e['rule_id'],e['timecode_sec']) for e in r['violations']]==[('outsider_in_cashroom',2)]
