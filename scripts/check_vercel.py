"""Test the hosted app with the CLI's existing deployment access. No secrets print."""
import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CLI = str(Path.home() / '.local/node/bin/vercel')


def request(url, path, body=None):
    command = [CLI, 'curl', url.rstrip('/')+path, '--scope', 'thehien04s-projects', '--',
        '--silent', '--show-error', '--max-time', '100', '--write-out', '\n%{http_code}']
    if body is not None:
        command += ['--request', 'POST', '--header', 'Content-Type: application/json', '--data-binary', '@-']
    start = time.monotonic()
    result = subprocess.run(command, input=json.dumps(body) if body else None,
        cwd=ROOT / '.build/vercel', capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Request failed: '+path)
    content, status = result.stdout.rsplit('\n', 1)
    print(json.dumps({'path':path, 'status':status, 'bytes':len(content.encode()),
        'seconds':round(time.monotonic()-start, 2)}), flush=True)
    assert status == '200', content[:400]
    assert len(content.encode()) < 2_000_000
    return json.loads(content)


def check(url):
    config = request(url, '/app/config')
    release = config['release_id']
    assert len(config['areas']) == 238 and config['page_size'] == 1000
    year = request(url, '/v2/hotspots/years/query', {'release_id':release,'area_name':'World','year':2024,'page_size':1})
    assert (year['unique_active_cells'], year['total_cell_days']) == (656093,11233633)
    base = {'release_id':release,'area_name':'North America','start_date':'2024-02-27',
        'end_date':'2024-02-29','page_size':1000}
    first = request(url, '/v2/hotspots/ranges/query', base)
    assert first['total_cell_days'] == 5422 and first['unique_active_cells'] == 4362
    assert len(first['features']) == 1000 and first['next_offset'] == 1000
    second = request(url, '/v2/hotspots/ranges/query', {**base,'offset':1000})
    assert {f['id'] for f in first['features']}.isdisjoint(f['id'] for f in second['features'])
    overlap = request(url, '/v2/hotspots/ranges/query', {**base,'start_date':'2024-02-28','include_geometry':False})
    assert overlap['total_cell_days'] == 3366 and overlap['unique_active_cells'] == 2947
    country = request(url, '/v2/hotspots/ranges/query', {**base,'area_name':'Viet Nam','start_date':'2024-01-01',
        'end_date':'2024-12-31','include_geometry':False})
    assert country['total_cell_days'] == 71684 and country['unique_active_cells'] == 3634
    chat = request(url, '/v2/chat/query', {'question':'Compare the selected ranges.', 'compare_selected':True,
        'area_name':'North America','ranges':[{'start_date':'2024-02-27','end_date':'2024-02-29'},
        {'start_date':'2024-02-28','end_date':'2024-02-29'}]})
    assert [item['total_cell_days'] for item in chat['data']] == [5422,3366]
    print(json.dumps({'checks_passed':True,'hosted_chat_available':chat['available'],'answer':chat['answer']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    check(parser.parse_args().url)
