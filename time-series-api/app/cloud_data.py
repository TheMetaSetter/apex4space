"""Blob -> one checked month -> cell/day totals -> remove the temporary file."""
from collections import Counter
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path, PurePosixPath
import threading
import time
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import duckdb
import httpx
from app.models import ApiError

_SLOT = threading.BoundedSemaphore(1)


def blob_url(manifest, item):
    base = os.environ.get('FRISM_BLOB_BASE_URL', '')
    parsed = urlparse(base)
    path = PurePosixPath(item['path'])
    if (parsed.scheme != 'https' or not parsed.hostname or
            not parsed.hostname.endswith('.public.blob.vercel-storage.com') or
            parsed.query or parsed.fragment or path.is_absolute() or '..' in path.parts):
        raise ApiError(503, 'STORAGE_UNAVAILABLE', 'The checked cloud data store is not set up.')
    return base.rstrip('/') + '/' + item['path']


def download_month(manifest, item, target, deadline):
    """Never keep an unchecked or oversized download, including an HTML error page."""
    digest, size = hashlib.sha256(), 0
    if item['bytes'] > 64_000_000:
        raise ApiError(503, 'SOURCE_TOO_LARGE', 'This monthly file exceeds the cloud limit.')
    with httpx.stream('GET', blob_url(manifest, item), timeout=min(10, max(0.1, deadline-time.monotonic())), trust_env=False) as response:
        response.raise_for_status()
        with target.open('wb') as output:
            for block in response.iter_bytes(262144):
                size += len(block)
                if size > item['bytes'] or time.monotonic() > deadline:
                    raise ApiError(503, 'QUERY_TIMEOUT', 'Choose a shorter date range and try again.')
                digest.update(block)
                output.write(block)
    if size != item['bytes'] or digest.hexdigest() != item['sha256']:
        raise ApiError(503, 'SOURCE_CHANGED', 'The monthly file does not match the checked release.')


@contextmanager
def checked_month(manifest, item, deadline):
    with TemporaryDirectory(prefix='frism-month-') as scratch:
        target = Path(scratch) / 'month.parquet'
        download_month(manifest, item, target, deadline)
        with duckdb.connect(config={'memory_limit': '384MB', 'threads': 1,
                'temp_directory': scratch, 'max_temp_directory_size': '256MB'}) as database:
            database.read_parquet(str(target), hive_partitioning=False).create_view('fires')
            timer = threading.Timer(max(0.01, deadline-time.monotonic()), database.interrupt)
            timer.start()
            try:
                yield database
            finally:
                timer.cancel()


def range_counts(manifest, start, end, codes):
    """Months have disjoint dates. Union countries inside each month before adding."""
    if not _SLOT.acquire(timeout=1):
        raise ApiError(503, 'QUERY_BUSY', 'A data query is running. Please try again.')
    cells, days, deadline = Counter(), {}, time.monotonic()+50
    downloaded = 0
    try:
        for item in manifest['sources']:
            if item['date_start'] >= str(end) or item['date_end'] < str(start):
                continue
            if time.monotonic() >= deadline:
                raise ApiError(503, 'QUERY_TIMEOUT', 'Choose a shorter date range and try again.')
            with checked_month(manifest, item, deadline) as database:
                downloaded += item['bytes']
                database.execute('''CREATE TEMP TABLE memberships AS SELECT DISTINCT acq_date,grid_id
                    FROM fires WHERE acq_date>=? AND acq_date<?
                    AND country_code IN (SELECT unnest(?))''', [start, end, codes])
                cells.update(dict(database.execute('SELECT grid_id,count(*) FROM memberships GROUP BY 1').fetchall()))
                days.update({str(day): count for day, count in database.execute(
                    'SELECT acq_date,count(*) FROM memberships GROUP BY 1').fetchall()})
        return tuple(sorted(cells.items())), days
    except (httpx.HTTPError, duckdb.Error) as error:
        raise ApiError(503, 'CLOUD_QUERY_UNAVAILABLE',
            'Cloud data is unavailable or the query reached its limit. Try a shorter range later.') from error
    finally:
        import json
        import resource
        print(json.dumps({'event': 'frism_query', 'download_bytes': downloaded,
            'elapsed_seconds': round(time.monotonic()-(deadline-50), 3),
            'peak_rss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 if os.name == 'posix' and os.uname().sysname == 'Linux' else 1048576), 1)}), flush=True)
        _SLOT.release()
