import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_parquet_data import parquet_client
from app.areas import load_world_areas, resolve_area_name
from app.ranges import intersects_view, statistics
from datetime import date


def test_global_lookup_has_data_without_invalid_outline():
    catalog=load_world_areas(Path(__file__).parents[1]/'config/global')
    assert resolve_area_name(catalog,'World')['id']=='world'
    assert resolve_area_name(catalog,'viet nam')['id']=='country:VNM'
    assert resolve_area_name(catalog,'USA')['id']=='country:USA'
    assert catalog['areas']['country:EGY']['geometry'] is None
    assert resolve_area_name(catalog,'Egypt')['country_codes']==['EGY']
    assert len(catalog['areas']['world']['country_codes'])==230
    assert set(catalog['areas']['continent:asia']['country_codes']).isdisjoint(catalog['areas']['continent:south-america']['country_codes'])


def test_world_union_and_country_queries(parquet_client):
    client,release,_=parquet_client
    client.app.state.world_areas=load_world_areas(Path(__file__).parents[1]/'config/global')
    body={'release_id':release,'area_name':'World','start_date':'2024-02-27','end_date':'2024-02-29'}
    world=client.post('/v2/hotspots/ranges/query',json=body).json()
    assert world['total_cell_days']==3 and world['unique_active_cells']==3
    usa=client.post('/v2/hotspots/ranges/query',json={**body,'area_name':'USA'}).json()
    canada=client.post('/v2/hotspots/ranges/query',json={**body,'area_name':'Canada'}).json()
    assert usa['total_cell_days']+canada['total_cell_days']==4
    assert client.post('/v2/hotspots/ranges/query',json={**body,'area_name':'Egypt'}).json()['total_cell_days']==0
    assert client.post('/v2/hotspots/ranges/query',json={**body,'area_name':'Atlantis'}).status_code==404
    page=client.post('/v2/hotspots/ranges/query',json={**body,'bbox':[170,-10,-170,10]}).json()
    assert page['visible_active_cells']==0 and page['total_cell_days']==3


def test_date_line_and_cross_year_statistics():
    assert intersects_view('E3857_10K_R0_C2003',(170,-10,-170,10))
    assert intersects_view('E3857_10K_R0_C-2004',(170,-10,-170,10))
    assert not intersects_view('E3857_10K_R0_C0',(170,-10,-170,10))
    data=statistics(date(2023,12,31),date(2024,1,2),[('cell',2)],{'2023-12-31':1,'2024-01-01':1})
    assert data['selected_days']==2 and data['monthly_counts']=={'2023-12':1,'2024-01':1}
