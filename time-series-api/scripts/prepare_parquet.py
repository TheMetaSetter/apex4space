"""Validate monthly country/cell/day Parquet and publish metadata, not a data copy."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import os

import duckdb

GRID = {'grid_version': 'firms-mercator-10km-v1', 'projection': 'EPSG:3857',
        'size_m': 10000, 'origin_m': [0, 0], 'index_rule': 'floor',
        'earth_radius_m': 6378137.0, 'latitude_limit': 85.0511287798066,
        'id_pattern': 'E3857_10K_R{row}_C{column}'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def check_month(connection, path, root):
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    connection.read_parquet(str(path), hive_partitioning=True).create_view('month_data', replace=True)
    schema = connection.execute('DESCRIBE month_data').fetchall()
    columns = {row[0]: row[1] for row in schema}
    if columns != {'acq_date': 'DATE', 'country_code': 'VARCHAR', 'grid_id': 'VARCHAR', 'month': 'BIGINT', 'year': 'BIGINT'}:
        raise ValueError(f'Unexpected schema: {path}')
    rows, start, end, nulls, wrong_partition, bad_ids, duplicates = connection.execute('''SELECT
        count(*),min(acq_date),max(acq_date),
        count(*) FILTER(WHERE acq_date IS NULL OR country_code IS NULL OR country_code='' OR grid_id IS NULL),
        count(*) FILTER(WHERE year!=year(acq_date) OR month!=month(acq_date)),
        count(*) FILTER(WHERE NOT regexp_full_match(grid_id,'E3857_10K_R-?[0-9]+_C-?[0-9]+')),
        count(*)-count(DISTINCT (acq_date,country_code,grid_id)) FROM month_data''').fetchone()
    if not rows or nulls or wrong_partition or bad_ids or duplicates:
        raise ValueError(f'Invalid month: {path}; null={nulls}, partition={wrong_partition}, grid={bad_ids}, duplicate={duplicates}')
    out_of_bounds = connection.execute('''SELECT count(*) FROM month_data WHERE
        CAST(regexp_extract(grid_id,'R(-?[0-9]+)',1) AS BIGINT) NOT BETWEEN -2004 AND 2003 OR
        CAST(regexp_extract(grid_id,'C(-?[0-9]+)',1) AS BIGINT) NOT BETWEEN -2004 AND 2003''').fetchone()[0]
    if out_of_bounds:
        raise ValueError(f'Grid outside the supplied Mercator limits: {path}')
    countries = dict(connection.execute('SELECT country_code,count(*) FROM month_data GROUP BY 1').fetchall())
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'Source changed while validating: {path}')
    return {'path': path.relative_to(root).as_posix(), 'bytes': before.st_size, 'mtime_ns': before.st_mtime_ns,
            'sha256': digest, 'rows': rows, 'date_start': str(start), 'date_end': str(end), 'countries': countries}


def build_metadata(source, sources, catalog, producer):
    members = json.loads((Path(catalog) / 'continent-membership.json').read_text())['north-america']
    codes = sorted(item.split(':')[1] for item in members)
    months = sorted({item['date_start'][:7] for item in sources})
    first, last = months[0], months[-1]
    expected = (int(last[:4]) - int(first[:4])) * 12 + int(last[5:]) - int(first[5:]) + 1
    if len(months) != expected:
        raise ValueError('A monthly partition is missing; do not treat missing input as zero.')
    countries = {}
    for item in sources:
        for code, count in item['countries'].items():
            countries[code] = countries.get(code, 0) + count
    inventory = [{'path': item['path'], 'sha256': item['sha256']} for item in sources]
    identity = {'format': 'parquet-country-grid-v1', 'grid': GRID, 'files': inventory,
                'membership_rule': 'detection_within_country_before_grid', 'north_america_codes': codes}
    release_id = hashlib.sha256(canonical(identity)).hexdigest()
    manifest = {'schema_version': 3, 'format': identity['format'], 'release_id': release_id,
        'snapshot_sha256': release_id, 'grid_policy_version': GRID['grid_version'], 'grid': GRID,
        'memberships_by_grid': {GRID['grid_version']: sum(item['rows'] for item in sources)},
        'source_root': str(source), 'sources': sources, 'countries': countries, 'north_america_codes': codes,
        'date_start': min(item['date_start'] for item in sources), 'date_end': max(item['date_end'] for item in sources),
        'rows_read': sum(item['rows'] for item in sources), 'file_count': len(sources),
        'membership_rule': identity['membership_rule'], 'duckdb_version': duckdb.__version__,
        'producer_script_sha256': hashlib.sha256(Path(producer).read_bytes()).hexdigest(),
        'coverage': 'unknown', 'source_limitations': ['Unmatched and boundary points excluded by within join.',
            'Invalid dates/coordinates and latitudes outside Mercator limits were discarded by producer.',
            'Raw detections and rejected rows cannot be recovered.', 'Grid is projected, not equal-area.',
            'Provided script explains the grid; original country-file identity and raw source inventory are unavailable.']}
    report = {'status': 'passed', 'checked_files': len(sources), 'checked_rows': manifest['rows_read'],
        'nulls': 0, 'partition_mismatches': 0, 'invalid_grid_ids': 0, 'out_of_bounds_cells': 0,
        'duplicate_country_cell_days': 0, 'north_america_country_rows': sum(countries.get(code, 0) for code in codes),
        'north_america_codes_without_records': sorted(set(codes) - countries.keys())}
    return manifest, report


def publish(source, output, catalog, producer):
    source, output = Path(source).resolve(strict=True), Path(output).absolute()
    if output.exists():
        raise ValueError('Choose a new output directory.')
    paths = sorted(source.glob('year=*/month=*/*.parquet'))
    if not paths or len(paths) != len(list(source.rglob('*.parquet'))):
        raise ValueError('Expected year/month partition folders.')
    if len({path.parent for path in paths}) != len(paths):
        raise ValueError('This validator requires one file per month; combine or validate multi-file partitions first.')
    sources = []
    with duckdb.connect(config={'memory_limit': '512MB', 'threads': 2}) as connection:
        for index, path in enumerate(paths, 1):
            sources.append(check_month(connection, path, source))
            if index % 30 == 0:
                print(f'Checked {index}/{len(paths)} monthly files', flush=True)
    manifest, report = build_metadata(source, sources, catalog, producer)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.parquet-', dir=output.parent))
    (stage / 'manifest.json').write_bytes(canonical(manifest) + b'\n')
    (stage / 'validation.json').write_bytes(canonical(report) + b'\n')
    os.rename(stage, output)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--producer-script', required=True)
    args = parser.parse_args()
    publish(args.input, args.output_dir, args.catalog, args.producer_script)
