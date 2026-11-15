"""Run the local web app and API with one command."""
import os
from pathlib import Path
import secrets
import sys
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'time-series-api'))
os.environ.setdefault('CURSOR_SECRET', secrets.token_hex(32))

if __name__ == '__main__':
    uvicorn.run('app.web:create_web_app', factory=True, host='127.0.0.1', port=8000)
