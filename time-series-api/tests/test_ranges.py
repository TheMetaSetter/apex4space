from test_parquet_data import parquet_client
import pytest


def test_inclusive_ranges_and_overlap(parquet_client):
    client, release, _ = parquet_client
    base = {'release_id':release,'area_name':'North America'}
    def query(start,end,**extra):
        response=client.post('/v2/hotspots/ranges/query',json={**base,'start_date':start,'end_date':end,**extra})
        assert response.status_code==200,response.text
        return response.json()
    a=query('2024-02-27','2024-02-29',page_size=1)
    assert a['selected_days']==3 and a['total_cell_days']==3 and a['average_daily_active_cells']==1
    assert len(a['days'])==3 and a['days'][1]['active_cell_count']==0
    b=query('2024-02-28','2024-02-29')
    assert b['total_cell_days']==2 and b['selected_days']==2
    assert query('2024-02-29','2024-02-29')['total_cell_days']==2
    assert query('2024-02-27','2024-02-27')['total_cell_days']==1
    assert query('2024-02-27','2024-02-29',offset=a['next_offset'],page_size=1)['features'][0]['id']!=a['features'][0]['id']
    assert query('2024-02-27','2024-02-29',include_geometry=False)['features']==[]
    assert query('2024-02-27','2024-02-29',bbox=[100,10,110,20])['total_cell_days']==3
    assert query('2024-02-27','2024-02-29',bbox=[100,10,110,20])['visible_active_cells']==0
    assert client.post('/v2/hotspots/ranges/query',json={**base,'start_date':'2024-03-01','end_date':'2024-02-29'}).status_code==422
    assert client.post('/v2/hotspots/ranges/query',json={**base,'start_date':'2023-01-01','end_date':'2024-02-29'}).status_code==422


@pytest.mark.parametrize('planned_ranges',[[],[{'start_date':'2024-02-27','end_date':'2024-02-29'}]])
def test_chat_keeps_overlapping_ranges_independent(parquet_client,monkeypatch,planned_ranges):
    import json
    client,release,_=parquet_client
    async def model(messages,schema=None):
        if schema:return json.dumps({'kind':'compare_ranges','area_name':'North America','years':[],'ranges':planned_ranges})
        assert '"total_cell_days": 3' in messages[1]['content']
        assert '"total_cell_days": 2' in messages[1]['content']
        return 'Both ranges keep their shared dates.'
    monkeypatch.setattr('app.insights._ollama',model)
    ranges=[{'start_date':'2024-02-27','end_date':'2024-02-29'},{'start_date':'2024-02-28','end_date':'2024-02-29'}]
    response=client.post('/v2/chat/query',json={'question':'Compare these ranges','ranges':ranges})
    assert response.status_code==200,response.text
    assert [item['total_cell_days'] for item in response.json()['data']]==[3,2]


def test_range_crosses_month_and_year_partitions(parquet_client):
    import json
    import duckdb
    from pathlib import Path
    from prepare_parquet import publish
    client,_,path=parquet_client
    root=path.parents[2]
    for year,month,day in [(2023,12,'2023-12-31'),(2024,1,'2024-01-01')]:
        folder=root/f'year={year}'/f'month={month}';folder.mkdir(parents=True)
        with duckdb.connect() as db:
            db.execute("COPY (SELECT CAST(? AS DATE) acq_date,'USA' country_code,'E3857_10K_R0_C0' grid_id) TO ? (FORMAT PARQUET)",[day,str(folder/'data_0.parquet')])
    output=root.parent/'multi-release'
    publish(root,output,Path(__file__).parents[1]/'config/north-america',root.parent/'producer.txt')
    release=json.loads((output/'manifest.json').read_text())['release_id']
    storage=client.app.state.settings.storage.model_copy(update={'global_release_path':output})
    client.app.state.settings=client.app.state.settings.model_copy(update={'storage':storage})
    body={'release_id':release,'area_name':'North America','start_date':'2023-12-31','end_date':'2024-01-01'}
    data=client.post('/v2/hotspots/ranges/query',json=body).json()
    assert data['selected_days']==2 and data['unique_active_cells']==1 and data['total_cell_days']==2
    assert data['features'][0]['properties']['active_days']==2
    data=client.post('/v2/hotspots/ranges/query',json={**body,'start_date':'2024-01-01','end_date':'2024-02-29'}).json()
    assert data['selected_days']==60 and data['total_cell_days']==4


def test_compare_selected_skips_model_reinterpretation(parquet_client,monkeypatch):
    import json
    client,_,_=parquet_client
    async def model(messages,schema=None):
        assert schema is None
        assert '"total_cell_days": 3' in messages[1]['content']
        return 'The selected ranges each have 3 cell-days.'
    monkeypatch.setattr('app.insights._ollama',model)
    period={'start_date':'2024-02-27','end_date':'2024-02-29'}
    response=client.post('/v2/chat/query',json={'question':'How do these two ranges compare?','compare_selected':True,'ranges':[period,period]})
    assert response.status_code==200,response.text
    assert [d['total_cell_days'] for d in response.json()['data']]==[3,3]
