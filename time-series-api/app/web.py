"""Serve the small local map beside the existing read-only API."""
import json
from pathlib import Path
from fastapi import Request
from fastapi.staticfiles import StaticFiles
from shapely.geometry import mapping
from app.main import create_app


def create_web_app():
    app = create_app()

    @app.get('/app/config', include_in_schema=False)
    def web_config(request: Request):
        directory = request.app.state.settings.storage.global_release_path
        manifest = json.loads((directory / 'manifest.json').read_text())
        catalog = request.app.state.world_areas
        features = []
        for area_id in ('country:VNM', 'continent:south-america'):
            area = catalog['areas'][area_id]
            features.append({'type': 'Feature', 'properties': {'area_id': area_id},
                             'geometry': mapping(area['geometry'].simplify(0.02, preserve_topology=True))})
        return {'release_id': manifest['release_id'], 'start_date': manifest['date_start'],
                'end_date': manifest['date_end'], 'boundaries': {'type': 'FeatureCollection', 'features': features}}

    app.mount('/', StaticFiles(directory=Path(__file__).resolve().parents[2] / 'web-app', html=True), name='web')
    return app
