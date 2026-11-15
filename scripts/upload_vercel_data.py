"""Upload only checked monthly files. Existing identical release paths are reused."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TEAM = 'thehien04s-projects'
CLI = str(Path.home() / '.local/node/bin/vercel')


def upload(item, manifest, stage, environment):
    path = Path(manifest['source_root']) / item['path']
    if path.stat().st_size != item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        raise ValueError('Source changed: '+item['path'])
    pathname = f"firms/{manifest['release_id']}/{item['path']}"
    result = subprocess.run([CLI, 'blob', 'put', str(path), '--pathname', pathname,
        '--access', 'public', '--no-multipart', '--scope', TEAM], cwd=stage, env=environment,
        capture_output=True, text=True)
    output = result.stdout+result.stderr
    if result.returncode and 'already exists' not in output:
        # Do not print provider output that might contain credentials.
        raise RuntimeError('Blob upload failed: '+item['path'])
    print('Ready: '+item['path'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', action='store_true', help='Upload one month for the first smoke test')
    arguments = parser.parse_args()
    stage = ROOT / '.build/vercel'
    environment = os.environ.copy()
    for line in (stage / '.vercel/.env.preview.local').read_text().splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            if key == 'BLOB_READ_WRITE_TOKEN':
                environment[key] = shlex.split(value)[0] if value else ''
    environment.pop('VERCEL_OIDC_TOKEN', None)
    environment.pop('BLOB_STORE_ID', None)
    release = ROOT / 'time-series-api/data/areas/world/parquet-v1'
    manifest = json.loads((release / 'manifest.json').read_text())
    manifest['source_root'] = str((release / manifest['source_root']).resolve())
    if sum(item['bytes'] for item in manifest['sources']) > 900_000_000:
        raise ValueError('The release exceeds the free storage budget')
    items = manifest['sources'][:1] if arguments.first else manifest['sources']
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item: upload(item, manifest, stage, environment), items))
