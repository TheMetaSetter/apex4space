"""Verify Parquet semantics independently of the existing equal-area database."""
import hashlib
import json
import os
from pathlib import Path
import sys

import duckdb
from fastapi.testclient import TestClient
from pyproj import Transformer
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from prepare_parquet import publish
from app.parquet_data import cell_feature


@pytest.fixture
def parquet_client(tmp_path, monkeypatch):
    root = tmp_path / 'data'
    month = root / 'year=2024/month=2'
    month.mkdir(parents=True)
    path = month / 'data_0.parquet'
    with duckdb.connect() as db:
        db.execute('''CREATE TABLE fires(acq_date DATE,country_code VARCHAR,grid_id VARCHAR)''')
        # The same border cell belongs to both countries; continent counts it once.
        db.executemany('INSERT INTO fires VALUES(?,?,?)', [
            ('2024-02-27','USA','E3857_10K_R-1_C-1'),
            ('2024-02-27','CAN','E3857_10K_R-1_C-1'),
            ('2024-02-29','USA','E3857_10K_R1_C1'),
            ('2024-02-29','CAN','E3857_10K_R2_C2')])
        db.execute('COPY fires TO ? (FORMAT PARQUET)', [str(path)])
    catalog = Path(__file__).parents[1] / 'config/north-america'
    release = tmp_path / 'release'
    producer = tmp_path / 'producer.txt'; producer.write_text('grid formula fixture')
    publish(root, release, catalog, producer)
    manifest = json.loads((release / 'manifest.json').read_text())
    manifest['source_root'] = '../data'
    (release / 'manifest.json').write_text(json.dumps(manifest))
    settings = json.loads((Path(__file__).parents[1] / 'config/settings.json').read_text())
    settings['storage'].update(data_format='parquet', global_release_path=str(release), world_areas_path=str(catalog))
    settings['api']['allowed_hosts'] = ['testserver']
    config = tmp_path / 'settings.json'; config.write_text(json.dumps(settings))
    monkeypatch.setenv('CURSOR_SECRET','parquet-test-secret-more-than-32-bytes')
    from app.main import create_app
    with TestClient(create_app(config)) as client:
        yield client, manifest['release_id'], path


def test_country_union_geometry_and_signed_paging(parquet_client):
    client, release, _ = parquet_client
    body = {'release_id':release,'area_name':'North America','date':'2024-02-29','page_size':1}
    response = client.post('/v2/hotspots/query', json=body)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first['active_cell_count'] == 2 and first['returned_count'] == 1
    assert first['source_projection'] == 'EPSG:3857' and first['equal_area'] is False
    second = client.post('/v2/hotspots/query', json={**body,'cursor':first['next_cursor']}).json()
    assert second['has_more'] is False and second['features'][0]['id'] != first['features'][0]['id']
    assert client.post('/v2/hotspots/query',json={**body,'cursor':first['next_cursor'],'area_name':'USA'}).status_code == 422
    assert client.post('/v2/hotspots/query',json={**body,'date':'2024-02-27'}).json()['active_cell_count'] == 1
    assert client.post('/v2/hotspots/query',json={**body,'area_name':'USA','date':'2024-02-27'}).json()['active_cell_count'] == 1


def test_leap_partial_empty_and_annual_totals(parquet_client):
    client, release, _ = parquet_client
    data = client.post('/v2/hotspots/years/query',json={'release_id':release,'area_name':'North America','year':2024,'page_size':1}).json()
    assert data['total_cell_days'] == 3 and data['unique_active_cells'] == 3
    assert len(data['days']) == 366 and data['complete_year'] is False
    assert data['monthly_cell_days'][1] == 3
    days = {day['date']:day['active_cell_count'] for day in data['days']}
    assert days['2024-01-01'] is None and days['2024-02-28'] == 0 and days['2024-02-29'] == 2
    assert data['features'][0]['properties']['grid_version'] == 'firms-mercator-10km-v1'
    summary = client.post('/v2/hotspots/summaries/query',json={'release_id':release,'area_name':'North America','start_date':'2024-02-27','end_date':'2024-03-01'}).json()
    assert [day['active_cell_count'] for day in summary['days']] == [1,0,2]
    assert summary['days'][1]['input_state'] == 'no_records'
    assert client.post('/v2/hotspots/query',json={'release_id':release,'area_name':'North America','date':'2023-01-01'}).status_code == 422


def test_corner_formula_and_world_edge_clip():
    inverse = Transformer.from_crs(3857,4326,always_xy=True)
    ring = cell_feature('E3857_10K_R-1_C-1')['geometry']['coordinates'][0]
    assert ring[0] == pytest.approx(inverse.transform(-10000,-10000))
    assert ring[2] == pytest.approx([0,0]) and ring[0] == ring[-1]
    edge = cell_feature('E3857_10K_R2003_C-2004')['geometry']['coordinates'][0]
    assert all(-180<=lon<=180 and -85.052<=lat<=85.052 for lon,lat in edge)


def test_chat_receives_parquet_results_and_provenance(parquet_client, monkeypatch):
    client, release, _ = parquet_client
    async def model(messages, schema=None):
        if schema:
            return json.dumps({'kind':'yearly','area_name':'North America','years':[2024]})
        assert '"total_cell_days": 3' in messages[1]['content']
        assert 'EPSG:3857' in messages[1]['content']
        return 'The selected data has 3 cell-days.'
    monkeypatch.setattr('app.insights._ollama',model)
    data = client.post('/v2/chat/query',json={'question':'How active was 2024?','years':[2024]}).json()
    assert data['data'][0]['total_cell_days'] == 3
    assert data['sources'][0]['release_id'] == release
    assert data['sources'][0]['membership_rule'] == 'detection_within_country_before_grid'


def test_changed_source_is_rejected_even_after_caching(parquet_client):
    client, release, path = parquet_client
    body = {'release_id':release,'area_name':'North America','year':2024}
    assert client.post('/v2/hotspots/years/query',json=body).status_code == 200
    path.write_bytes(path.read_bytes()+b'changed')
    assert client.post('/v2/hotspots/years/query',json=body).status_code == 503


def test_git_checkout_time_uses_source_hash(parquet_client):
    client, release, path = parquet_client
    before = path.stat()
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    body = {'release_id':release,'area_name':'North America','year':2024}
    assert client.post('/v2/hotspots/years/query',json=body).status_code == 200
    content = path.read_bytes()
    path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    assert client.post('/v2/hotspots/years/query',json=body).status_code == 503


def test_validator_rejects_cross_row_duplicate(tmp_path):
    root = tmp_path/'input/year=2024/month=2';root.mkdir(parents=True)
    path=root/'data_0.parquet'
    with duckdb.connect() as db:
        db.execute("COPY (SELECT DATE '2024-02-29' acq_date,'USA' country_code,'E3857_10K_R0_C0' grid_id FROM range(2)) TO ? (FORMAT PARQUET)",[str(path)])
    from prepare_parquet import check_month
    with duckdb.connect() as db, pytest.raises(ValueError,match='duplicate=1'):
        check_month(db,path,tmp_path/'input')
