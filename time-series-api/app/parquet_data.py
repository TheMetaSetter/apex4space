"""Read the checked country/grid/day Parquet through fixed parameterized queries."""
from contextlib import contextmanager
from datetime import date, timedelta
from functools import lru_cache
import json
import hashlib
import math
import time
from pathlib import Path
import threading
from tempfile import TemporaryDirectory

import duckdb
from app.models import ApiError

GRID_VERSION = 'firms-mercator-10km-v1'
GRID_META = {'grid_version': GRID_VERSION, 'source_projection': 'EPSG:3857',
    'cell_size_m': 10000, 'membership_rule': 'detection_within_country_before_grid',
    'equal_area': False, 'geometry_rule': 'Nominal projected cell clipped at Mercator world edges for display.'}
_QUERY_SLOTS = threading.BoundedSemaphore(2)


@lru_cache(maxsize=512)
def _source_hash(path, size, modified_ns):
    """Check a relocated file once; repeat only when its size or time changes."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest_for(settings, release_id=None):
    try:
        directory = settings.storage.global_release_path
        manifest = json.loads((directory / 'manifest.json').read_text())
        if manifest['format'] != 'parquet-country-grid-v1' or manifest['grid_policy_version'] != GRID_VERSION:
            raise ValueError('Unsupported Parquet format')
        identity = {'format': manifest['format'], 'grid': manifest['grid'],
            'files': [{'path': item['path'], 'sha256': item['sha256']} for item in manifest['sources']],
            'membership_rule': manifest['membership_rule'], 'north_america_codes': manifest['north_america_codes']}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if digest != manifest['release_id'] or digest != manifest['snapshot_sha256']:
            raise ValueError('Release identity does not match its source inventory')
        if release_id is not None and release_id != manifest['release_id']:
            raise ApiError(409, 'UNSUPPORTED_SCHEMA', 'The requested release is not selected.')
        if manifest.get('storage') == 'vercel-blob':
            from app.cloud_data import blob_url
            for item in manifest['sources']:
                blob_url(manifest, item)
            return manifest
        root = (directory / manifest['source_root']).resolve(strict=True)
        for item in manifest['sources']:
            path = (root / item['path']).resolve(strict=True)
            if not path.is_relative_to(root):
                raise ValueError('Source escapes the release root')
            stat = path.stat()
            if stat.st_size != item['bytes']:
                raise ValueError('Source changed after validation')
            if stat.st_mtime_ns != item['mtime_ns'] and _source_hash(path, stat.st_size, stat.st_mtime_ns) != item['sha256']:
                raise ValueError('Source hash changed after validation')
        # The checked source can travel with the repository; queries use its resolved path.
        manifest['source_root'] = str(root)
        return manifest
    except ApiError:
        raise
    except (OSError, KeyError, ValueError, TypeError) as error:
        raise ApiError(503, 'DATABASE_UNAVAILABLE', 'The checked Parquet release is missing or changed. Validate it again.') from error


def _country_codes(manifest, area_id):
    if area_id == 'world':
        return sorted(manifest['countries'])
    if area_id == 'continent:north-america':
        return manifest['north_america_codes']
    code = area_id.removeprefix('country:')
    if code not in manifest['countries']:
        raise ApiError(404, 'AREA_NOT_FOUND', 'The requested area is not available in the source data.')
    return [code]


@contextmanager
def _read_months(manifest, start, end):
    """Open only intersecting monthly files. No persistent DuckDB database is created."""
    if not _QUERY_SLOTS.acquire(timeout=2):
        raise ApiError(503, 'QUERY_BUSY', 'Two data queries are running. Please try again.')
    try:
        paths = [str(Path(manifest['source_root']) / item['path']) for item in manifest['sources']
                 if item['date_start'] < str(end) and item['date_end'] >= str(start)]
        if not paths:
            yield None
            return
        with TemporaryDirectory(prefix='frism-duckdb-') as scratch, duckdb.connect(config={
                'memory_limit':'512MB','threads':2,'temp_directory':scratch,'max_temp_directory_size':'2GB'}) as connection:
            connection.read_parquet(paths, hive_partitioning=True).create_view('fires')
            timer = threading.Timer(30, connection.interrupt)
            timer.start()
            try:
                yield connection
            finally:
                timer.cancel()
    except duckdb.Error as error:
        raise ApiError(503, 'QUERY_TIMEOUT' if isinstance(error, duckdb.InterruptException) else 'QUERY_FAILED',
            'The query exceeded its time or memory limit. Choose a shorter range or smaller area.') from error
    finally:
        _QUERY_SLOTS.release()


def cell_feature(grid_id, active_days=None):
    """Keep source indices; transform cell corners, rather than assigning a new grid."""
    row_text, column_text = grid_id.removeprefix('E3857_10K_R').split('_C')
    row, column = int(row_text), int(column_text)
    radius, limit = 6378137.0, math.pi * 6378137.0
    def corner(column_index, row_index):
        x = max(-limit, min(limit, column_index * 10000))
        y = max(-limit, min(limit, row_index * 10000))
        return [max(-180.0, min(180.0, math.degrees(x / radius))),
                math.degrees(2 * math.atan(math.exp(y / radius)) - math.pi / 2)]
    ring = [corner(column, row), corner(column + 1, row), corner(column + 1, row + 1),
            corner(column, row + 1), corner(column, row)]
    properties = {'grid_version': GRID_VERSION, 'cell_id': grid_id}
    if active_days is not None:
        properties.update(active_days=active_days, polar=False)
    return {'type': 'Feature', 'id': f'{GRID_VERSION}:{grid_id}', 'properties': properties,
            'geometry': {'type': 'Polygon', 'coordinates': [ring]}}


def provenance(manifest, area):
    return {'release_id': manifest['release_id'], 'area_id': area['id'], 'area_name': area['name'],
        'source_dates': [manifest['date_start'], manifest['date_end']], 'coverage': 'unknown',
        'metric': 'active 10 km projected cells; cell-days count each cell once per UTC day',
        **GRID_META}


def _check_date_range(manifest, start, end):
    if str(start) < manifest['date_start'] or str(end - timedelta(days=1)) > manifest['date_end']:
        raise ApiError(422, 'DATE_UNAVAILABLE', 'The dates are outside the imported range.',
            details={'start': manifest['date_start'], 'end': manifest['date_end']})


def daily(query, request):
    # Late imports keep the existing SQLite routes independent of this reader.
    from app.area_queries import _area, _cursor, _decode_cursor
    catalog = request.app.state.world_areas
    area = _area(catalog, query)
    manifest = manifest_for(request.app.state.settings, query.release_id)
    _check_date_range(manifest, query.date, query.date + timedelta(days=1))
    after = _decode_cursor(query.cursor, request.app.state.cursor_secret, manifest, area, catalog, query) if query.cursor else None
    codes = area.get('country_codes') or _country_codes(manifest, area['id'])
    rows, _ = _range_counts(str(request.app.state.settings.storage.global_release_path),
        manifest['release_id'], area['id'], str(query.date), str(query.date + timedelta(days=1)), tuple(area.get('country_codes',())))
    keys = [key for key, count in rows]
    candidates = [key for key in keys if after is None or [GRID_VERSION, key] > after]
    selected, more = candidates[:query.page_size], len(candidates) > query.page_size
    cursor = _cursor(request.app.state.cursor_secret, manifest, area, catalog, query, [GRID_VERSION, selected[-1]]) if more else None
    return {**provenance(manifest, area), 'catalog_version': catalog['version'], 'date': str(query.date),
        'grid_versions': [GRID_VERSION], 'active_cell_count': len(keys), 'status': 'coverage_unknown',
        'warnings': ['Coverage unknown; zero records do not prove no fire.', 'EPSG:3857 projected cells are not equal-area.'],
        'type': 'FeatureCollection', 'features': [cell_feature(key) for key in selected],
        'returned_count': len(selected), 'has_more': more, 'next_cursor': cursor}


def summaries(query, request):
    from app.area_queries import _area
    catalog = request.app.state.world_areas
    area = _area(catalog, query)
    manifest = manifest_for(request.app.state.settings, query.release_id)
    _check_date_range(manifest, query.start_date, query.end_date)
    codes = area.get('country_codes') or _country_codes(manifest, area['id'])
    _, daily_counts = _range_counts(str(request.app.state.settings.storage.global_release_path),
        manifest['release_id'], area['id'], str(query.start_date), str(query.end_date), tuple(codes))
    counts = {date.fromisoformat(day): count for day, count in daily_counts.items()}
    days, day = [], query.start_date
    while day < query.end_date:
        days.append({'date': str(day), 'active_cell_count': counts.get(day, 0), 'status': 'coverage_unknown',
                     'input_state': 'records_present' if day in counts else 'no_records'})
        day += timedelta(days=1)
    return {**provenance(manifest, area), 'catalog_version': catalog['version'],
        'start_date': str(query.start_date), 'end_date': str(query.end_date), 'days': days}


@lru_cache(maxsize=1)
def _range_counts(directory, release_id, area_id, start_text, end_text, country_codes=()):
    manifest = json.loads((Path(directory) / 'manifest.json').read_text())
    codes = list(country_codes) if country_codes else _country_codes(manifest, area_id)
    start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    if manifest.get('storage') == 'vercel-blob':
        from app.cloud_data import range_counts
        return range_counts(manifest, start, end, codes)
    manifest['source_root'] = str((Path(directory) / manifest['source_root']).resolve())
    if (end-start).days>366:
        return _long_range(directory,release_id,area_id,start,end,country_codes)
    with _read_months(manifest, start, end) as db:
        if db is None:
            return (), {}
        rows = db.execute('''WITH memberships AS (SELECT DISTINCT acq_date,grid_id FROM fires
            WHERE acq_date>=? AND acq_date<? AND country_code IN (SELECT unnest(?)))
            SELECT grid_id,count(*) FROM memberships GROUP BY grid_id ORDER BY grid_id''', [start, end, codes]).fetchall()
        daily_counts = dict(db.execute('''SELECT acq_date,count(DISTINCT grid_id) FROM fires
            WHERE acq_date>=? AND acq_date<? AND country_code IN (SELECT unnest(?)) GROUP BY 1''', [start, end, codes]).fetchall())
    return tuple(rows), {str(day): count for day, count in daily_counts.items()}


def _long_range(directory,release_id,area_id,start,end,country_codes):
    # Years have disjoint dates: add per-cell active-day counts, never country totals.
    cells,days={},{}
    deadline=time.monotonic()+30
    while start<end:
        if time.monotonic()>deadline:
            raise ApiError(503,'QUERY_TIMEOUT','The range exceeded 30 seconds. Choose a shorter range or smaller area.')
        stop=min(end,date(start.year+1,1,1))
        rows,part=_range_counts(directory,release_id,area_id,str(start),str(stop),country_codes)
        for grid,count in rows:cells[grid]=cells.get(grid,0)+count
        days.update(part);start=stop
    return tuple(sorted(cells.items())),days


def _year_counts(directory, release_id, area_id, year, country_codes=()):
    return _range_counts(directory, release_id, area_id, f'{year}-01-01', f'{year+1}-01-01', country_codes)


def year_result(query, request, include_page=False):
    from app.area_queries import _area
    from app.insights import _year_summary
    area = _area(request.app.state.world_areas, query)
    manifest = manifest_for(request.app.state.settings, query.release_id)
    if query.year < int(manifest['date_start'][:4]) or query.year > int(manifest['date_end'][:4]):
        raise ApiError(422, 'DATE_UNAVAILABLE', 'The year is outside the imported range.')
    directory = str(request.app.state.settings.storage.global_release_path)
    saved = Path(directory) / 'summaries' / area['id'].replace(':', '-') / f'{query.year}.json'
    if manifest.get('storage') == 'vercel-blob' and saved.exists() and (not include_page or query.page_size == 1 and query.offset == 0):
        data = json.loads(saved.read_text())
        if data.pop('release_id') != manifest['release_id']:
            raise ApiError(503, 'SOURCE_CHANGED', 'The calendar does not match this release.')
        if not include_page:
            data.pop('features', None)
        return data, provenance(manifest, area)
    rows, days = _year_counts(directory, manifest['release_id'], area['id'], query.year, tuple(area.get('country_codes',())))
    data = _year_summary(manifest, query.year, days, [])
    stop = query.offset + query.page_size
    data.update(unique_active_cells=len(rows), next_offset=stop if stop < len(rows) else None)
    if include_page:
        data['features'] = [cell_feature(grid, count) for grid, count in rows[query.offset:stop]]
    return data, provenance(manifest, area)


def year_page(query, request):
    data, source = year_result(query, request, include_page=True)
    return {**data, **source, 'type': 'FeatureCollection'}
