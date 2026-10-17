"""Presentation-only legal context. A text check is not a violation finding."""

SOURCE_TITLES = {
    'https://adilet.zan.kz/rus/docs/V1900019680':
        'Постановление Правления НБРК от 29.11.2019 № 231 — Правила осуществления кассовых операций и операций по инкассации (сокращённое название)',
    'https://adilet.zan.kz/rus/docs/V2000020075':
        'Постановление Правления НБРК от 24.02.2020 № 14 — Правила организации охраны и устройства помещений (сокращённое название)',
}


def rule_metadata(rule):
    return {
        'rule_title':rule['title'],
        'source':rule.get('source'),
        'source_title':rule.get('source_title') or SOURCE_TITLES.get(rule.get('source')),
        'paragraph':rule.get('paragraph'),
        # Legacy flag means an established normative binding, never merely PDF matching.
        'source_verified':False,
        'source_text_verified':bool(rule.get('source_text_verified',False)),
        'source_current_verified':False,
        'source_snapshot':rule.get('source_snapshot'),
        'source_pages':list(rule.get('source_pages',[])),
        'source_checked_on':rule.get('source_checked_on'),
        'basis_type':rule.get('basis_type','unreviewed'),
        'requirement':rule.get('requirement'),
        'applicability':rule.get('applicability'),
        'limits':rule.get('limits'),
        'legal_status':rule.get('legal_status','Нормативная привязка не подтверждена.'),
    }
