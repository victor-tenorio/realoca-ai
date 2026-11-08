"""Separate read-only demo surface. Never import this in the original app."""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if 'app.db' in sys.modules:
    raise RuntimeError('Public demo must run in its own fresh process.')
SNAPSHOT = ROOT / '.public-demo' / 'snapshot.db'
DIST = ROOT / 'frontend' / 'dist'
if not SNAPSHOT.is_file() or not (DIST / 'index.html').is_file():
    raise RuntimeError('Existing snapshot and compiled frontend required.')
# Set before importing any module that initializes the SQLAlchemy engine.
os.environ['DATABASE_URL'] = f'sqlite:///file:{SNAPSHOT.as_posix()}?mode=ro&uri=true'
os.environ['DEMO_REFERENCE_DATE'] = '2026-11-08'
for key in list(os.environ):
    if key.startswith(('N8N_', 'SLACK_')):
        os.environ.pop(key, None)

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.api.v1 import audit, cases, dashboard, employees, health, tasks, teams
from app.errors import register_error_handlers

app = FastAPI(title='Realoca AI public read-only demo', docs_url=None,
              redoc_url=None, openapi_url=None)
register_error_handlers(app)
for module in (employees, tasks, teams, cases, dashboard, audit):
    app.include_router(module.router, prefix='/api/v1')
app.include_router(health.router)
# No mutating handler is registered, even behind the middleware.
app.router.routes[:] = [route for route in app.router.routes
                       if getattr(route, 'methods', set()) <= {'GET', 'HEAD'}]
ALLOWED_API = re.compile(r'^/api/v1/(employees|tasks|teams|cases|dashboard|audit|cases/case-[a-zA-Z0-9-]+)$')

@app.middleware('http')
async def public_boundary(request: Request, call_next):
    if request.method not in {'GET', 'HEAD'}:
        return JSONResponse({'error': {'code': 'PUBLIC_DEMO_READ_ONLY',
                             'message': 'Demo pública somente leitura.'}}, status_code=405,
                            headers={'Allow': 'GET, HEAD'})
    path = request.url.path
    if path not in {'/', '/health', '/favicon.ico'} and not path.startswith('/assets/') and not ALLOWED_API.fullmatch(path):
        return JSONResponse({'error': {'code': 'NOT_FOUND'}}, status_code=404)
    response = await call_next(request)
    response.headers['X-Realoca-Mode'] = 'public-read-only'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.get('/', response_class=HTMLResponse)
def index():
    html = (DIST / 'index.html').read_text(encoding='utf-8')
    notice = ('<aside role="status" style="padding:12px;background:#fff3cd;color:#493b00;'
              'text-align:center;font:14px system-ui">DEMO PÚBLICA · SOMENTE LEITURA · '
              'Dados sintéticos persistidos. Nenhuma ação envia mensagens. '
              'O Simulador Slack é interativo e apenas local.</aside>')
    return html.replace('<body>', '<body>' + notice)

app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')
