"""Generated notes must remain bounded, cached and tied to measured evidence."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from birdframe.public_insights import field_notes, facts_for


def _site():
    bird = {'slug': 'robin', 'name': 'European Robin', 'scientific': 'Erithacus rubecula',
            'days': 14, 'count': 400, 'first': '2026-07-01', 'last': '2026-07-14',
            'history': [['2026-07-14', 40]], 'recent': 200, 'previous': 100}
    return {'species': [bird], 'days': [{'day': '2026-07-14', 'count': 40, 'species': 1}],
            'listeningDays': 14, 'season': None}


def _client(make):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=make)))


def test_notes_use_public_evidence_and_reuse_persisted_result(tmp_path):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        content = json.dumps({'notes': [{'fact_id': 'lead', 'title': 'A familiar voice leads',
            'body': 'The robin leads the latest record; explore its daily rhythm.'}]})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    site, path, now = _site(), tmp_path / 'notes.json', datetime(2026, 7, 14, 15)
    first = field_notes(site, path, client=_client(create), now=now)
    assert first['mode'] == 'generated'
    assert first['notes'][0]['title'] == 'Which voice leads the latest day?'
    assert first['notes'][0]['title'] != 'A familiar voice leads'
    assert '40 of 40' in first['notes'][0]['evidence']
    assert first['notes'][0]['href'] == '#b-robin'
    assert calls[0]['response_format']['json_schema']['strict'] is True
    assert calls[0]['max_completion_tokens'] == 700
    again = field_notes(site, path, client=_client(create), now=now + timedelta(hours=7))
    assert again == first and len(calls) == 1  # unchanged facts need no fresh request
    site['days'][0]['count'] = 50
    fresh = field_notes(site, path, client=_client(create), now=now + timedelta(minutes=5))
    assert fresh['mode'] == 'data' and len(calls) == 1
    assert any('50' in fact['evidence'] for fact in fresh['questions'])


def test_failed_generation_reserves_attempt_across_restarts(tmp_path):
    calls = []

    def fail(**kwargs):
        calls.append(1)
        raise OSError('offline')

    path, now = tmp_path / 'notes.json', datetime(2026, 7, 14, 15)
    assert field_notes(_site(), path, client=_client(fail), now=now)['mode'] == 'data'
    field_notes(_site(), path, client=_client(fail), now=now + timedelta(hours=1))
    assert len(calls) == 1
    field_notes(_site(), path, client=_client(fail), now=now + timedelta(hours=6))
    assert len(calls) == 2


def test_unknown_sources_or_invented_numeric_claims_are_rejected(tmp_path):
    for i, note in enumerate([
        {'fact_id': 'unavailable', 'title': 'An invented source', 'body': 'This does not have a measured source.'},
        {'fact_id': 'lead', 'title': 'One hundred birds', 'body': 'There were 100 individual birds in the garden.'},
    ]):
        def create(**kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'notes': [note]})))])
        assert field_notes(_site(), tmp_path / f'{i}.json', client=_client(create),
                           now=datetime(2026, 7, 14))['mode'] == 'data'


def test_no_model_is_needed_for_guided_questions():
    result = field_notes(_site())
    assert result['mode'] == 'data'
    assert result['questions'] == facts_for(_site())
    assert len(result['notes']) == 3
