import json
from pathlib import Path
import pytest
from forte.rule_metadata import rule_metadata
from forte.coverage import rule_checks

CATALOG=json.loads(Path('config/rules.json').read_text(encoding='utf-8'))
CFG=json.loads(Path('config/scene.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('rule_id',CFG['enabled_rules'])
def test_active_rule_has_complete_distinct_normative_context(rule_id):
    rule=CATALOG[rule_id]
    meta=rule_metadata(rule)
    assert meta['rule_title'].startswith('Контроль ')
    assert all(meta[k] for k in ['requirement','applicability','limits','legal_status','basis_type'])
    assert meta['source_verified'] is False
    assert meta['source_current_verified'] is False
    if meta['source']:
        assert meta['source']=='https://adilet.zan.kz/rus/docs/V1900019680'
        if rule_id=='no_client_id':
            assert meta['source_text_verified'] is False
            assert meta['basis_type']=='visual_control_unverified_reference'
            assert not meta['source_pages'] and not meta['source_snapshot']
        else:
            assert meta['source_text_verified'] is True
            assert meta['source_pages'] and meta['source_snapshot']
    else:
        assert meta['source_text_verified'] is False and meta['paragraph'] is None


def test_explicit_exceptions_and_no_invented_sources():
    bag=CATALOG['bag_left_by_visitor']
    assert 'нарушением целостности' in bag['applicability']
    assert 'не определяются' in bag['limits']
    assert 'не имеющих' in CATALOG['phone_with_camera']['requirement']
    assert 'не к блокноту или пустой ёмкости' in CATALOG['desk_materials_left']['applicability']
    for key in ['pc_not_shutdown','food_at_workplace','several_clients','camera_obstructed','possible_incomplete_cash_return']:
        assert CATALOG[key]['source'] is None


def test_static_catalog_copies_and_coverage_metadata_agree():
    for name in ['forte_с_правилами','forte_без_правил']:
        assert json.loads((Path('frontend')/name/'rules.json').read_text(encoding='utf-8'))==CATALOG
    checks=rule_checks(CATALOG,CFG['enabled_rules'],[],{},10)
    for check in checks:
        for key,value in rule_metadata(CATALOG[check['rule_id']]).items():
            assert check[key]==value


def test_manual_rule_does_not_inherit_pdf_verification():
    assert CATALOG['bag_opened_without_collector']['mode']=='manual_review'
    meta=rule_metadata(CATALOG['bag_opened_without_collector'])
    assert not meta['source_text_verified'] and meta['basis_type']=='unreviewed'
    assert len(CATALOG)==33 and len(CFG['enabled_rules'])==20


def test_cash_check_candidate_does_not_claim_manual_recount_recognition():
    rule=CATALOG['no_count_check']
    assert rule['event_title']=='Проверка банкнот после счётной машины требует перепроверки'
    assert rule['paragraph']=='п. 19, пп. 2); п. 57'
    assert rule['mode']=='automatic_candidate'
    assert rule['basis_type']=='mixed_basis'
    assert rule['source_pages']==[6,10]
    assert 'нет прямого требования' in rule['applicability']
    assert 'no_count_check' in CFG['enabled_rules']
    assert 'Ручной полистный пересчёт автоматически не оценивается' in rule['description']
    checks=rule_checks(CATALOG,CFG['enabled_rules'],[],{},100)
    check=next(item for item in checks if item['rule_id']=='no_count_check')
    assert check['status']=='insufficient_evidence'
    assert not check['event_times_sec']
    assert CATALOG['food_at_workplace']['event_title']!=rule['event_title']
