"""Verify the built React bundle is served by FastAPI; never uses an auth bypass."""
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import create_app

bundle = Path(__file__).resolve().parents[2] / 'frontEnd' / 'dist'
with TestClient(create_app(bundle)) as client:
    page = client.get('/')
    assert page.status_code == 200 and 'text/html' in page.headers['content-type']
    assert 'onboarding' in page.text
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page.text)
    assert assets, 'No compiled frontend assets found'
    for asset in assets:
        response = client.get(asset)
        assert response.status_code == 200
        assert 'text/html' not in response.headers['content-type']
    assert client.get('/research').status_code == 200
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/api/not-a-route').status_code == 404
    response = client.post('/api/ai/ask', json={'question': 'Who founded Microsoft and in what year?'})
    assert response.status_code == 401 and 'application/json' in response.headers['content-type']
    print('PASS: Built React HTML/assets, SPA routes, health, API JSON authentication, and API 404 routing.')
