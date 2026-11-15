"""Make a small deploy folder. No source data, local settings or secrets are copied."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / 'time-series-api'
RELEASE = API / 'data/areas/world/parquet-v1'
sys.path.insert(0, str(API))


def calendars():
    from app.areas import load_world_areas
    from app.insights import YearQuery
    from app.models import load_settings
    from app.parquet_data import year_result
    settings = load_settings(API / 'config/settings.json')
    catalog = load_world_areas(settings.storage.world_areas_path)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings, world_areas=catalog)))
    manifest = json.loads((RELEASE / 'manifest.json').read_text())
    for area in ('World', 'North America'):
        area_id = 'world' if area == 'World' else 'continent-north-america'
        destination = RELEASE / 'summaries' / area_id
        destination.mkdir(parents=True, exist_ok=True)
        for year in range(int(manifest['date_start'][:4]), int(manifest['date_end'][:4])+1):
            target = destination / f'{year}.json'
            if target.exists() and json.loads(target.read_text()).get('release_id') == manifest['release_id']:
                continue
            query = YearQuery(release_id=manifest['release_id'], area_name=area, year=year, page_size=1)
            data, _ = year_result(query, request, include_page=True)
            target.write_text(json.dumps({**data, 'release_id': manifest['release_id']}, separators=(',', ':')))
            print(f'Calendar ready: {area} {year}', flush=True)


def stage(destination):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(API / 'app', destination / 'app', dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(API / 'config/global', destination / 'config/global', dirs_exist_ok=True)
    release = destination / 'data/release'
    release.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((RELEASE / 'manifest.json').read_text())
    manifest.pop('source_root')
    manifest['storage'] = 'vercel-blob'
    (release / 'manifest.json').write_text(json.dumps(manifest))
    if (RELEASE / 'summaries').exists():
        shutil.copytree(RELEASE / 'summaries', release / 'summaries', dirs_exist_ok=True)
    settings = json.loads((API / 'config/settings.json').read_text())
    settings['storage'].update(global_release_path='data/release', world_areas_path='config/global')
    settings['api'].update(allowed_hosts=['*.vercel.app', 'localhost', '127.0.0.1', 'testserver'], maximum_page_size=1000)
    (destination / 'config/cloud.json').write_text(json.dumps(settings))
    public = destination / 'public'
    public.mkdir(exist_ok=True)
    for name in ('index.html', 'app.js', 'style.css', 'world.geojson', 'Frism-logo-cream.png', 'vendor'):
        source, target = ROOT / 'web-app' / name, public / name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    html = (public / 'index.html').read_text()
    for name in ('style.css', 'app.js'):
        digest = hashlib.sha256((public / name).read_bytes()).hexdigest()[:12]
        html = html.replace(f'"{name}"', f'"{name}?v={digest}"')
    (public / 'index.html').write_text(html)
    (destination / 'index.py').write_text('from app.cloud import create_cloud_app\napp = create_cloud_app()\n')
    (destination / '.python-version').write_text('3.13\n')
    (destination / '.vercelignore').write_text('.vercel\n**/__pycache__\n**/*.pyc\n')
    (destination / 'requirements.txt').write_text('\n'.join(
        ['fastapi==0.162.6', 'pydantic==2.14.3', 'httpx==0.28.1', 'shapely==2.2.0', 'pyproj==3.7.2', 'duckdb==2.0.0'])+'\n')
    (destination / 'vercel.json').write_text(json.dumps({'$schema': 'https://openapi.vercel.sh/vercel.json',
        'framework': 'fastapi', 'functions': {'index.py': {'maxDuration': 300}},
        'headers': [{'source': '/vendor/(.*)', 'headers': [{'key': 'Cache-Control', 'value': 'public, max-age=86400'}]}]}))
    size = sum(path.stat().st_size for path in destination.rglob('*') if path.is_file() and '.vercel' not in path.parts)
    if size > 20_000_000:
        raise ValueError('Source bundle exceeds 20 MB; inspect before deploying')
    print(f'Deploy source: {destination} ({size:,} bytes)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calendars', action='store_true', help='Precompute World and North America calendars first')
    parser.add_argument('--output', type=Path, default=ROOT / '.build/vercel')
    arguments = parser.parse_args()
    if arguments.calendars:
        calendars()
    stage(arguments.output.resolve())
