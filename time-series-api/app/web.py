"""Serve the small local map beside the existing read-only API."""
import json
from pathlib import Path
from fastapi import Request
from fastapi.staticfiles import StaticFiles
from shapely.geometry import mapping
from app.main import create_app


def create_web_app(settings_path=None, serve_static=True):
    app = create_app(settings_path)

    @app.get('/app/config', include_in_schema=False)
    def web_config(request: Request):
        directory = request.app.state.settings.storage.global_release_path
        manifest = json.loads((directory / 'manifest.json').read_text())
        if request.app.state.settings.storage.data_format == 'parquet':
            from app.parquet_data import manifest_for, GRID_META
            manifest = manifest_for(request.app.state.settings)
            grid = GRID_META
        else:
            grid = {'source_projection': 'EPSG:6933/6931/6932', 'cell_size_m': 10000, 'equal_area': True, 'membership_rule': 'cell_center_within_country'}
        catalog = request.app.state.world_areas
        features = []
        for area_id in catalog['areas']:
            if area_id == 'country:VNM' and 'world' not in catalog['areas']:
                continue
            area = catalog['areas'][area_id]
            if area['geometry'] is None:
                continue
            features.append({'type': 'Feature', 'properties': {'area_id': area_id},
                             'geometry': mapping(area['geometry'].simplify(0.02 if serve_static else 0.1, preserve_topology=True))})
        return {'cloud': not serve_static, 'page_size': 1000, 'grid': grid, 'data_format': request.app.state.settings.storage.data_format, 'release_id': manifest['release_id'], 'start_date': manifest['date_start'],
                'end_date': manifest['date_end'], 'areas': [{'id': item['id'], 'name': item['name'], 'bbox': item.get('bbox'), 'aliases': [key for key, ids in catalog['aliases'].items() if item['id'] in ids]} for item in catalog['areas'].values() if item['id'] != 'country:VNM' or 'world' in catalog['areas']],
                'boundaries': {'type': 'FeatureCollection', 'features': features}}

    if serve_static:
        app.mount('/', StaticFiles(directory=Path(__file__).resolve().parents[2] / 'web-app', html=True), name='web')
    return app
