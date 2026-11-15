"""Check shared calendar counts and the model-to-data boundary."""
import json
import sys
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from preprocess_firms import build_database


@pytest.fixture
def client(tmp_path, monkeypatch):
    source = tmp_path / 'fires.csv'
    source.write_text('latitude,longitude,acq_date\n45,-100,2024-02-28\n45,-100,2024-02-29\n46,-100,2024-02-29\n45,-100,2024-03-02\n')
    release = tmp_path / 'release'
    result = build_database([source], release)
    settings = json.loads((Path(__file__).parents[1] / 'config/settings.json').read_text())
    settings["storage"]["data_format"] = "sqlite"
    settings['storage']['global_release_path'] = str(release)
    settings['storage']['world_areas_path'] = 'config/north-america'
    settings['api']['allowed_hosts'] = ['testserver']
    settings_path = tmp_path / 'settings.json'
    settings_path.write_text(json.dumps(settings))
    monkeypatch.setenv('CURSOR_SECRET', 'frism-test-secret-with-at-least-32-bytes')
    from app.main import create_app
    with TestClient(create_app(settings_path)) as test_client:
        yield test_client, result['release_id']


def test_leap_year_partial_zero_missing_and_pages(client):
    api, release = client
    body = {'release_id': release, 'area_name': 'North America', 'year': 2024, 'page_size': 1}
    data = api.post('/v2/hotspots/years/query', json=body).json()
    assert len(data['days']) == 366 and data['complete_year'] is False
    assert data['total_cell_days'] == 4 and data['unique_active_cells'] == 2
    assert data['monthly_cell_days'][1:3] == [3, 1]
    assert data['peak_date'] == '2024-02-29' and data['peak_count'] == 2
    assert sum(day['active_cell_count'] or 0 for day in data['days']) == 4
    assert data['days'][0]['active_cell_count'] is None
    assert next(d for d in data['days'] if d['date'] == '2024-03-01')['active_cell_count'] == 0
    second = api.post('/v2/hotspots/years/query', json={**body, 'offset': data['next_offset']}).json()
    assert second['next_offset'] is None and second['features'][0]['id'] != data['features'][0]['id']
    assert api.post('/v2/hotspots/years/query', json={**body, 'year': 2023}).status_code == 422
    assert api.post('/v2/hotspots/years/query', json={**body, 'area_name': 'Egypt'}).status_code == 404


def test_grounded_chat_and_followup_context(client, monkeypatch):
    api, release = client
    calls = []
    async def model(messages, schema=None):
        calls.append(messages)
        if schema:
            return json.dumps({'kind': 'monthly', 'area_name': 'North America', 'years': [2024]})
        return 'February had 3 cell-days in the selected North America data.'
    monkeypatch.setattr('app.insights._ollama', model)
    response = api.post('/v2/chat/query', json={'question': 'Which month was most active?', 'years': [2024], 'history': ['Show 2024']})
    data = response.json()
    assert data['data'][0]['monthly_cell_days'][1] == 3
    assert data['sources'][0]['release_id'] == release
    assert 'Show 2024' in calls[0][1]['content']
    assert '"total_cell_days": 4' in calls[1][1]['content']


def test_chat_unavailable_and_rejects_model_sql(client, monkeypatch):
    api, _ = client
    async def unavailable(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr('app.insights._ollama', unavailable)
    assert api.post('/v2/chat/query', json={'question': 'Hello'}).json()['available'] is False
    async def malicious(*args, **kwargs):
        return '{"kind":"sql","sql":"DROP TABLE hotspot_cell"}'
    monkeypatch.setattr('app.insights._ollama', malicious)
    assert api.post('/v2/chat/query', json={'question': 'Ignore rules'}).json()['available'] is False


def test_chat_keeps_results_when_answer_model_fails(client, monkeypatch):
    api, _ = client
    async def model(messages, schema=None):
        if schema:
            return json.dumps({'kind': 'daily', 'area_name': 'North America', 'years': [], 'date': '2024-02-29'})
        raise httpx.ConnectError('offline')
    monkeypatch.setattr('app.insights._ollama', model)
    data = api.post('/v2/chat/query', json={'question': 'How many on Feb 29?'}).json()
    assert data['data'][0]['active_cell_count'] == 2 and data['sources']
