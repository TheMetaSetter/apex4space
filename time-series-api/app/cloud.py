"""Small Vercel entry point. Local settings and the local server stay separate."""
import os
from pathlib import Path

from starlette.responses import JSONResponse
from app.web import create_web_app


class ResponseLimit:
    """Send a clear error instead of a response larger than the cloud budget."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        messages, size = [], 0
        async def collect(message):
            nonlocal size
            size += len(message.get('body', b''))
            if size > 2_000_000:
                raise OverflowError('Cloud response limit')
            messages.append(message)
        try:
            await self.app(scope, receive, collect)
        except OverflowError:
            response = JSONResponse({'error': {'code': 'RESPONSE_TOO_LARGE',
                'message': 'Choose a shorter range or smaller map page.'}}, status_code=413)
            return await response(scope, receive, send)
        for message in messages:
            await send(message)


def create_cloud_app():
    os.environ['FRISM_CLOUD'] = '1'
    app = create_web_app(Path(__file__).parents[1] / 'config/cloud.json', serve_static=False)
    # Old SQLite endpoints have no data in this cloud release.
    app.router.routes = [route for route in app.router.routes
        if not route.path.startswith('/v1/') and route.path != '/health/ready']
    @app.get('/health/ready')
    def ready():
        from app.parquet_data import manifest_for
        manifest_for(app.state.settings)
        if app.state.world_areas is None:
            return JSONResponse({'status': 'catalog_unavailable'}, status_code=503)
        return {'status': 'ok', 'data_access': 'checked_on_query'}
    app.add_middleware(ResponseLimit)
    return app
