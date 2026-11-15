"""Production SPA routing must never shadow authenticated JSON API routes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from fastapi.testclient import TestClient
from app.main import create_app

class FrontendServingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'index.html').write_text('<html>React application</html>', encoding='utf-8')
        (self.root / 'assets').mkdir()
        (self.root / 'assets/app-123.js').write_text('console.log("bundle")', encoding='utf-8')
        (self.root / '.env').write_text('never serve this', encoding='utf-8')
        self.client = TestClient(create_app(self.root))
        self.addCleanup(self.client.close)

    def test_root_and_browser_route_serve_spa(self):
        for path in ('/', '/research', '/workspace/history'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('text/html', response.headers['content-type'])
            self.assertIn('React application', response.text)

    def test_health_and_authentication_keep_json(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})
        response = self.client.post('/api/ai/ask', json={'question': 'A research question?'})
        self.assertEqual(response.status_code, 401)
        self.assertIn('application/json', response.headers['content-type'])

    def test_unknown_api_and_missing_assets_do_not_fall_back_to_html(self):
        for path in ('/api', '/api/not-a-route', '/assets/missing.js', '/.env', '/assets/../.env'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)
            self.assertNotIn('React application', response.text)
            self.assertNotIn('never serve this', response.text)
        self.assertEqual(self.client.post('/api/not-a-route').status_code, 404)

    def test_actual_asset_is_served_as_javascript(self):
        response = self.client.get('/assets/app-123.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('javascript', response.headers['content-type'])

    def test_missing_bundle_fails_startup(self):
        with self.assertRaisesRegex(RuntimeError, 'index.html'):
            create_app(self.root / 'missing')

if __name__ == '__main__':
    unittest.main()
