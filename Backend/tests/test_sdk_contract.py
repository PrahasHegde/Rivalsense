"""Exercise the installed SDK and project imports without external requests."""
import importlib
import json
import os
import unittest
import warnings
from unittest.mock import patch

import httpx
from context.dev import ContextDev
from fastapi.testclient import TestClient
from app.services.context_client import scrape_product

URL = "https://shop.example.com/products/mug"


class SDKContractTests(unittest.TestCase):
    @patch.dict(os.environ, {"CONTEXT_DEV_API_KEY": "test-placeholder"})
    def test_real_sdk_serialization_and_response_fields(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={
                "url": URL, "isPartial": True,
                "product": {"requested": True, "success": True, "data": {
                    "isProductPage": True, "product": {
                        "name": "Travel Mug", "brand": None, "price": 19.99, "sku": "MUG-100",
                        "currency": "EUR", "availability": "in_stock",
                        "dimensions": [], "features": [], "images": [], "tags": [],
                        "targetAudience": [], "variants": []}}}})

        real_client = ContextDev(api_key="test-placeholder", timeout=60, max_retries=0,
                                 http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        with patch("app.services.context_client.ContextDev", return_value=real_client):
            result = scrape_product(URL)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/v1/web/scrape")
        body = json.loads(requests[0].content)
        self.assertEqual(body["maxAgeMs"], 0)
        self.assertEqual(body["formats"], {"product": True})
        self.assertEqual(body["productParams"], {"dedupeImages": False})
        self.assertEqual(body["timeoutOpts"], {"milliseconds": 55000, "behavior": "return-partial"})
        self.assertEqual(body["zdr"], "disabled")
        self.assertTrue(result.is_partial)
        self.assertTrue(result.product.data.is_product_page)
        product = result.product.data.product
        self.assertEqual(product.name, "Travel Mug")
        self.assertIsNone(product.brand)
        self.assertEqual(product.price, 19.99)
        self.assertEqual(product.currency, "EUR")
        self.assertEqual(product.availability, "in_stock")
        self.assertEqual(product.sku, "MUG-100")

    def test_repeated_imports_preserve_routes_without_duplicates(self):
        module = importlib.import_module("app.main")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(2):
                module = importlib.reload(module)
                with TestClient(module.app) as client:
                    schema = client.get("/openapi.json").json()
                    self.assertIn("post", schema["paths"]["/api/prices/extract"])
                    self.assertIn("post", schema["paths"]["/api/prices/compare"])
                    self.assertEqual(client.get("/health").status_code, 200)
                    self.assertEqual(client.get("/").status_code, 200)
        self.assertFalse(any("Duplicate Operation ID" in str(item.message) for item in caught))
        # The normal Uvicorn entry point still exposes a FastAPI application.
        self.assertTrue(hasattr(importlib.import_module("main").app, "openapi"))
