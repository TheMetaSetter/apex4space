"""Shared read-only year queries and local, data-grounded educational chat."""
from contextlib import closing
from datetime import date, timedelta
from datetime import date as Date
from functools import lru_cache
import json
import os
import sqlite3
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from app.area_queries import _Query, _area, _database, _select_area_cells
from app.models import ApiError


class YearQuery(_Query):
    year: int = Field(ge=1900, le=2100)
    offset: int = Field(default=0, ge=0)
    page_size: int = Field(default=1000, ge=1, le=10000)


class ChatRange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start_date: Date
    end_date: Date


class ChatQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=1000)
    compare_selected: bool = False
    area_name: str = Field(default='North America', max_length=200)
    years: list[int] = Field(default_factory=list, max_length=2)
    ranges: list[ChatRange] = Field(default_factory=list, max_length=2)
    date: Date | None = None
    history: list[str] = Field(default_factory=list, max_length=6)


class DataIntent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['general', 'daily', 'monthly', 'yearly', 'compare', 'range', 'compare_ranges', 'clarify']
    area_name: str = Field(max_length=200)
    years: list[int] = Field(max_length=2)
    date: Date | None = None
    ranges: list[ChatRange] = Field(default_factory=list, max_length=2)
    clarification: str = Field(default='', max_length=500)


@lru_cache(maxsize=6)
def _year_data(directory, logical_hash, area_id, catalog_version, year, geometry_wkb):
    """Cache derived results only in memory; the published database is read-only."""
    from shapely import from_wkb
    manifest = json.loads((Path(directory) / 'manifest.json').read_text())
    if year < int(manifest['date_start'][:4]) or year > int(manifest['date_end'][:4]):
        raise ApiError(422, 'INVALID_QUERY', 'This year is outside the imported dates.')
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    with closing(sqlite3.connect((Path(directory) / 'database.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        # Area -> selected cells -> one row per cell/day -> year counts.
        import time
        deadline = time.monotonic() + 30
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        _select_area_cells(db, {'geometry': from_wkb(geometry_wkb)})
        rows = db.execute('''SELECT d.grid_version,d.cell_id,d.date FROM hotspot_cell_day d
            JOIN selected_area_cells s USING(grid_version,cell_id)
            WHERE d.release_id=? AND d.date>=? AND d.date<?''',
            (manifest['release_id'], start.isoformat(), end.isoformat()))
        counts, daily = {}, {}
        for grid, cell, day in rows:
            counts[grid, cell] = counts.get((grid, cell), 0) + 1
            daily[day] = daily.get(day, 0) + 1
        cells = []
        for grid, cell, geometry, latitude in db.execute('''SELECT c.grid_version,c.cell_id,c.geometry_json,c.center_latitude
            FROM hotspot_cell c JOIN selected_area_cells s USING(grid_version,cell_id) ORDER BY c.grid_version,c.cell_id'''):
            if (grid, cell) in counts:
                cells.append({'type': 'Feature', 'id': f'{grid}:{cell}', 'geometry': json.loads(geometry),
                    'properties': {'cell_id': cell, 'active_days': counts[grid, cell], 'polar': abs(latitude) > 86}})
    return _year_summary(manifest, year, daily, cells)


def _year_summary(manifest, year, daily, cells):
    days, monthly = [], [0] * 12
    current = date(year, 1, 1)
    while current.year == year:
        key = current.isoformat()
        available = manifest['date_start'] <= key <= manifest['date_end']
        count = daily.get(key, 0) if available else None
        days.append({'date': key, 'active_cell_count': count, 'status': 'coverage_unknown' if available else 'outside_release'})
        if count is not None:
            monthly[current.month - 1] += count
        current += timedelta(days=1)
    peak = max(daily, key=lambda key: (daily[key], key)) if daily else None
    return {'year': year, 'features': cells, 'days': days, 'monthly_cell_days': monthly,
        'unique_active_cells': len(cells), 'total_cell_days': sum(daily.values()),
        'peak_date': peak, 'peak_count': daily.get(peak, 0),
        'complete_year': manifest['date_start'] <= f'{year}-01-01' and manifest['date_end'] >= f'{year}-12-31',
        'polar_cells': sum(cell['properties']['polar'] for cell in cells)}


def year_result(query, request):
    if request.app.state.settings.storage.data_format == "parquet":
        from app.parquet_data import year_result as parquet_year
        return parquet_year(query, request)
    area = _area(request.app.state.world_areas, query)
    db, manifest = _database(request.app.state.settings, query.release_id)
    db.close()
    directory = request.app.state.settings.storage.global_release_path
    try:
        data = _year_data(str(directory), manifest['logical_sha256'], area['id'],
            request.app.state.world_areas['version'], query.year, area['geometry'].wkb)
    except sqlite3.OperationalError as error:
        raise ApiError(503, 'QUERY_TIMEOUT', 'The year query could not finish. Please try again.') from error
    return data, {'release_id': manifest['release_id'], 'area_name': area['name'],
        'area_id': area['id'], 'source_dates': [manifest['date_start'], manifest['date_end']],
        'metric': 'active 10 km cells; cell-days count one cell once per UTC day', 'coverage': 'unknown'}


def query_year(query: YearQuery, request: Request):
    if request.app.state.settings.storage.data_format == "parquet":
        from app.parquet_data import year_page
        return year_page(query, request)
    data, source = year_result(query, request)
    stop = query.offset + query.page_size
    return {**source, **data, 'type': 'FeatureCollection',
        'features': data['features'][query.offset:stop],
        'next_offset': stop if stop < len(data['features']) else None}


async def _ollama(messages, schema=None):
    if os.environ.get('FRISM_CLOUD') == '1':
        from app.cloud_chat import complete
        return await complete(messages, schema)
    payload = {'model': 'gemma4:e2b', 'messages': messages, 'stream': False, 'think': False,
               'options': {'temperature': 0.1, 'num_predict': 1000 if schema else 500}}
    if schema:
        payload['format'] = schema
        payload['messages'] = [*messages, {'role':'system','content':'Return only valid JSON matching this schema: '+json.dumps(schema)}]
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        response = await client.post('http://127.0.0.1:11434/api/chat', json=payload)
        response.raise_for_status()
        return response.json()['message']['content']


def _chat_data(intent, query, request, release_id):
    if intent.kind == 'general':
        return [], []
    if intent.kind == 'clarify':
        raise ApiError(422, 'CLARIFY', intent.clarification or 'Please choose an area and year.')
    if intent.kind in {'range','compare_ranges'} or (intent.kind=='compare' and query.ranges):
        return _chat_ranges(intent,query,request,release_id)
    years = intent.years or query.years
    if intent.kind == 'daily':
        if intent.date is None:
            raise ApiError(422, 'CLARIFY', 'Which date do you want?')
        years = [intent.date.year]
    if not years or (intent.kind == 'compare' and len(set(years)) != 2):
        raise ApiError(422, 'CLARIFY', 'Please choose two years to compare, or one year to explore.')
    context, sources = [], []
    for year in years:
        data, source = year_result(YearQuery(release_id=release_id, area_name=intent.area_name, year=year), request)
        stats = {key: value for key, value in data.items() if key not in {'features', 'days'}}
        if intent.kind == 'daily':
            stats = next(day for day in data['days'] if day['date'] == intent.date.isoformat())
        context.append(stats)
        sources.append({**source, 'year': year})
    return context, sources


def _chat_ranges(intent,query,request,release_id):
    from app.ranges import DateRange, range_result
    ranges=intent.ranges or query.ranges
    required=2 if intent.kind in {'compare','compare_ranges'} else 1
    if len(ranges)!=required and len(query.ranges)==required:
        ranges=query.ranges
    if not ranges or (intent.kind in {'compare','compare_ranges'} and len(ranges)!=2):
        raise ApiError(422,'CLARIFY','Please choose one range, or two ranges to compare.')
    context,sources=[],[]
    for period in ranges:
        data,source,_=range_result(DateRange(release_id=release_id,area_name=intent.area_name,
            start_date=period.start_date,end_date=period.end_date,include_geometry=False),request)
        context.append({k:v for k,v in data.items() if k!='days'})
        sources.append({**source,'start_date':data['start_date'],'end_date':data['end_date']})
    return context,sources


async def query_chat(query: ChatQuery, request: Request):
    catalog = request.app.state.world_areas
    allowed = [a['name'] for a in catalog['areas'].values() if a['id'] != 'country:VNM' or 'world' in catalog['areas']]
    manifest = json.loads((request.app.state.settings.storage.global_release_path / 'manifest.json').read_text())
    instruction = ('Classify this student question into the supplied JSON schema. Never generate SQL. '
        'Use current area, ranges, years and date if omitted. Use range or compare_ranges for selected date ranges. '
        'Leave ranges empty when the question refers to selected ranges; the server already has them. '
        'Overlapping ranges are independent. Use history for follow-ups. '
        'For unavailable areas or unclear questions use clarify. Available areas: ' + json.dumps(allowed))
    context = query.model_dump(mode='json')
    if query.compare_selected:
        intent=DataIntent(kind='compare_ranges',area_name=query.area_name,years=[])
    else:
        try:
            content = await _ollama([{'role': 'system', 'content': instruction},
                {'role': 'user', 'content': json.dumps(context)}], DataIntent.model_json_schema())
            intent = DataIntent.model_validate_json(content)
        except (httpx.HTTPError, ValueError, KeyError):
            if os.environ.get('FRISM_CLOUD') == '1':
                from app.cloud_chat import selected_summary
                return await run_in_threadpool(selected_summary, query, request, manifest['release_id'])
            return {'answer': 'Local chat unavailable. Start Ollama with gemma4:e2b and try again.',
                    'data': [], 'sources': [], 'available': False}
    data, sources = await run_in_threadpool(_chat_data, intent, query, request, manifest['release_id'])
    prompt = ('Write a short structured summary in simple English. Maximum 40 words total. '
        'Use exactly three short lines labeled Summary:, Key fact:, and Note:. '
        'Use plain text, no Markdown, no introduction, no repeated facts. '
        'Use only supplied data for numbers. '
        'Explain active cells are not fire counts; coverage is unknown. Use the supplied source grid definition. '
        'Projected Mercator cells are not equal-area. Do not infer causes or burned area. '
        'If there is no data, give general education only. Area and dates are displayed separately; do not repeat them.')
    try:
        answer = await _ollama([{'role': 'system', 'content': prompt},
            {'role': 'user', 'content': json.dumps({'question': query.question, 'history': query.history, 'data': data, 'sources': sources})}])
    except (httpx.HTTPError, ValueError, KeyError):
        from app.cloud_chat import summary
        answer = summary(data) if os.environ.get('FRISM_CLOUD') == '1' else 'Local chat unavailable. The retrieved database results are shown below.'
        return {'answer': answer, 'data': data, 'sources': sources, 'available': False}
    return {'answer': answer, 'data': data, 'sources': sources, 'available': True}
