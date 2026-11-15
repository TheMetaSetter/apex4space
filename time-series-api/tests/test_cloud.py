"""Cloud checks use tiny checked files, never the full remote dataset."""
from datetime import date
import hashlib
import json
from pathlib import Path
import time

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app import cloud_data
from app.cloud import ResponseLimit
from app.models import ApiError
from test_parquet_data import parquet_client


def test_month_union_hash_and_cleanup(tmp_path, monkeypatch):
    path = tmp_path / 'source.parquet'
    with duckdb.connect() as database:
        database.execute("COPY (SELECT DATE '2024-02-29' acq_date, code country_code, 'E3857_10K_R1_C1' grid_id FROM (VALUES ('USA'),('CAN')) t(code)) TO ? (FORMAT PARQUET)", [str(path)])
    content = path.read_bytes()
    item = {'path': 'year=2024/month=2/data_0.parquet', 'date_start': '2024-02-29',
        'date_end': '2024-02-29', 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    manifest = {'sources': [item]}
    monkeypatch.setenv('FRISM_BLOB_BASE_URL', 'https://test.public.blob.vercel-storage.com/release')
    folders = []
    original = cloud_data.TemporaryDirectory
    def temporary(**kwargs):
        folder = original(**kwargs)
        folders.append(Path(folder.name))
        return folder
    monkeypatch.setattr(cloud_data, 'TemporaryDirectory', temporary)
    def stream(*args, **kwargs):
        return httpx.Response(200, content=content, request=httpx.Request('GET', args[1]))
    monkeypatch.setattr(cloud_data.httpx, 'stream', stream)
    # Response needs the same context-manager contract as a streamed response.
    from contextlib import contextmanager
    @contextmanager
    def response(*args, **kwargs):
        yield stream(*args, **kwargs)
    monkeypatch.setattr(cloud_data.httpx, 'stream', response)
    rows, days = cloud_data.range_counts(manifest, date(2024,2,28), date(2024,3,1), ['USA','CAN'])
    assert rows == (('E3857_10K_R1_C1', 1),) and days == {'2024-02-29': 1}
    item['sha256'] = '0'*64
    with pytest.raises(ApiError) as failure:
        with cloud_data.checked_month(manifest, item, time.monotonic()+10):
            pytest.fail('Unchecked file reached SQL')
    assert failure.value.code == 'SOURCE_CHANGED'
    assert folders and all(not folder.exists() for folder in folders)


def test_response_limit_and_cloud_page_limit(monkeypatch):
    from app.ranges import DateRange
    monkeypatch.setenv('FRISM_CLOUD', '1')
    with pytest.raises(ValueError):
        DateRange(release_id='0'*64, area_name='World', start_date='2024-01-01', end_date='2024-01-01', page_size=1001)
    app = FastAPI()
    @app.get('/')
    def large():
        return {'large': 'x'*2_000_000}
    app.add_middleware(ResponseLimit)
    response = TestClient(app).get('/')
    assert response.status_code == 413 and len(response.content) < 300


def test_chat_fails_closed_when_model_has_a_price(monkeypatch):
    import asyncio
    from app import cloud_chat
    monkeypatch.setenv('AI_GATEWAY_API_KEY', 'test-only')
    monkeypatch.setenv('FRISM_HOSTED_CHAT', '1')
    monkeypatch.setattr(cloud_chat, '_price_checked_until', 0)
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            return httpx.Response(200, json={'data':[{'id':cloud_chat.MODEL,'pricing':{'input':'0','output':'1'}}]}, request=httpx.Request('GET',url))
        async def post(self, *args, **kwargs): pytest.fail('Paid model must never be called')
    monkeypatch.setattr(cloud_chat.httpx, 'AsyncClient', lambda **kwargs: Client())
    with pytest.raises(ValueError, match='no longer free'):
        asyncio.run(cloud_chat.complete([{'role':'user','content':'Hello'}]))


def test_cloud_chat_returns_exact_selected_data_without_ai(parquet_client, monkeypatch):
    client, release, _ = parquet_client
    monkeypatch.setenv('FRISM_CLOUD', '1')
    monkeypatch.delenv('FRISM_HOSTED_CHAT', raising=False)
    response = client.post('/v2/chat/query', json={'question':'Which month was most active?',
        'area_name':'North America','ranges':[{'start_date':'2024-02-27','end_date':'2024-02-29'}]})
    data = response.json()
    assert response.status_code == 200 and data['available'] is False
    assert data['data'][0]['total_cell_days'] == 3
    assert '2024-02: 3 cell-days' in data['answer']
    assert data['sources'][0]['release_id'] == release


def test_cloud_keeps_body_guard_and_uses_shared_rate_limit(parquet_client, monkeypatch):
    client, _, _ = parquet_client
    monkeypatch.setenv('FRISM_CLOUD', '1')
    for _ in range(65):
        assert client.get('/health/live').status_code == 200
    response = client.post('/v2/chat/query', content=json.dumps({'question':'x'*20000}),
        headers={'Content-Type':'application/json'})
    assert response.status_code == 413
