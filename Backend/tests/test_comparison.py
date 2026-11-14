"""Comparison tests mock provider responses and all URL network operations."""
import os
import socket
import unittest
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
from context.dev import APIConnectionError, APITimeoutError
from fastapi.testclient import TestClient
from app.main import app
from offline_support import authorize_functional_tests

URL = "https://shop.example.com/products/mug"
SECOND = "https://other.example.com/products/mug"


def page(url=URL, **changes):
    values = dict(name="Acme Mug M-100", brand="Acme", sku="MUG-100",
                  price=19.99, currency="EUR", availability="in_stock")
    values.update(changes)
    return NS(url=url, is_partial=False,
              product=NS(success=True, data=NS(is_product_page=True, product=NS(**values))))


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        authorize_functional_tests(self)
        patches = [
            patch.dict(os.environ, {"CONTEXT_DEV_API_KEY": "test-placeholder"}),
            patch("app.services.extraction.check_redirects", side_effect=lambda url: url),
            patch("app.services.url_safety.socket.getaddrinfo", return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]),
            patch("app.services.extraction.scrape_product", return_value=page()),
        ]
        for item in patches:
            result = item.start()
            self.addCleanup(item.stop)
        self.scrape = result
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def post(self, **changes):
        body = dict(product_name="Acme Mug M-100", selling_price="25.00", currency="EUR",
                    sku="MUG-100", competitor_urls=[URL])
        body.update(changes)
        return self.client.post("/api/prices/compare", json=body)

    def test_confirmed_sku_match_and_decimal_difference(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["comparable_count"], 1)
        row = data["competitors"][0]
        self.assertEqual(row["matching_status"], "confirmed")
        self.assertEqual(row["price_difference"], "5.01")
        self.assertEqual(row["price"], "19.99")
        self.assertEqual(row["source_url"], URL)
        self.assertEqual(row["sku"], "MUG-100")
        self.assertIsNotNone(row["observed_at"])

    def test_decimal_precision_and_negative_difference(self):
        self.scrape.return_value = page(price=0.1)
        self.assertEqual(self.post(selling_price="0.3").json()["competitors"][0]["price_difference"], "0.2")
        self.scrape.return_value = page(price=30.01)
        self.assertEqual(self.post().json()["competitors"][0]["price_difference"], "-5.01")

    def test_lowest_price_and_ties(self):
        self.scrape.side_effect = [page(price=20), page(SECOND, price=20)]
        data = self.post(competitor_urls=[URL, SECOND]).json()
        self.assertEqual(Decimal(data["lowest_competitor_price"]), Decimal("20"))
        self.assertEqual(data["lowest_competitor_source_urls"], [URL, SECOND])

    def test_cheaper_uncertain_or_wrong_currency_product_is_not_lowest(self):
        third = "https://third.example.com/products/mug"
        self.scrape.side_effect = [page(price=19.99), page(SECOND, name="Different Mug", price=1),
                                  page(third, price=0.5, currency="USD")]
        data = self.post(competitor_urls=[URL, SECOND, third]).json()
        self.assertEqual(data["comparable_count"], 1)
        self.assertEqual(data["lowest_competitor_price"], "19.99")
        self.assertEqual(data["lowest_competitor_source_urls"], [URL])

    def test_model_prefix_is_not_an_identifier_match(self):
        name = "Acme Mug M-100-PLUS"
        self.scrape.return_value = page(name=name)
        row = self.post(product_name=name, model_number="M-100").json()["competitors"][0]
        self.assertEqual(row["matching_status"], "needs_review")

    def test_name_only_requires_review(self):
        data = self.post(sku=None).json()
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["competitors"][0]["matching_status"], "needs_review")
        self.assertIsNone(data["lowest_competitor_price"])

    def test_model_and_brand_evidence(self):
        for changes in (dict(sku=None, model_number="M-100"), dict(sku=None, brand="Acme")):
            with self.subTest(changes=changes):
                self.assertEqual(self.post(**changes).json()["competitors"][0]["matching_status"], "confirmed")

    def test_model_boundaries_and_variants_need_review(self):
        for product in (page(name="Acme Mug M-1000"), page(name="Acme Mug M100"),
                        page(name="Acme Mug M-100 Red"), page(name=None)):
            self.scrape.return_value = product
            row = self.post(model_number="M-100").json()["competitors"][0]
            self.assertEqual(row["matching_status"], "needs_review")
            self.assertIsNone(row["price_difference"])

    def test_brand_conflict_and_sku_conflict(self):
        self.assertEqual(self.post(brand="Other").json()["competitors"][0]["matching_status"], "mismatch")
        self.scrape.return_value = page(sku="OTHER")
        self.assertEqual(self.post().json()["competitors"][0]["matching_status"], "needs_review")

    def test_missing_price_currency_and_different_currency_excluded(self):
        for changes in (dict(price=None), dict(currency=None), dict(currency="USD")):
            with self.subTest(changes=changes):
                self.scrape.return_value = page(**changes)
                data = self.post().json()
                self.assertEqual(data["comparable_count"], 0)
                self.assertIsNone(data["competitors"][0]["price_difference"])
                self.assertIsNone(data["lowest_competitor_price"])

    def test_zero_price_and_currency_case(self):
        self.scrape.return_value = page(price=0, currency="eur")
        data = self.post(currency="eur").json()
        self.assertEqual(data["currency"], "EUR")
        self.assertEqual(data["comparable_count"], 1)
        self.assertEqual(Decimal(data["lowest_competitor_price"]), 0)

    def test_failed_competitor_does_not_discard_success(self):
        error = APITimeoutError(request=httpx.Request("POST", "https://api.context.dev/v1/web/scrape"))
        self.scrape.side_effect = [error, page(SECOND)]
        data = self.post(competitor_urls=[URL, SECOND]).json()
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["comparable_count"], 1)
        failed = data["competitors"][0]
        self.assertEqual(failed["extraction_http_status"], 504)
        self.assertEqual(failed["extraction_status"], "failure")
        self.assertEqual(failed["matching_status"], "unavailable")
        self.assertIsNotNone(failed["extraction_error"])

    def test_all_failed_and_no_provider_error_leak(self):
        self.scrape.side_effect = APIConnectionError(message="secret-internal-detail", request=httpx.Request("POST", URL))
        response = self.post()
        self.assertEqual(response.json()["status"], "failure")
        self.assertNotIn("secret-internal-detail", response.text)
        self.assertNotIn("test-placeholder", response.text)

    def test_unsafe_urls_use_real_shared_validator(self):
        # Remove only the preflight mock; no target fetch occurs for these inputs.
        from app.services.url_safety import check_redirects
        with patch("app.services.extraction.check_redirects", side_effect=check_redirects):
            for url in ("https://127.0.0.1/p", "https://localhost/p", "http://example.com/p", "bad-url"):
                data = self.post(competitor_urls=[url]).json()
                self.assertEqual(data["status"], "failure")
                self.assertEqual(data["competitors"][0]["extraction_http_status"], 400)
        self.scrape.assert_not_called()

    def test_missing_key_returns_individual_errors(self):
        with patch.dict(os.environ, {"CONTEXT_DEV_API_KEY": ""}):
            data = self.post().json()
        self.assertEqual(data["competitors"][0]["extraction_http_status"], 503)
        self.scrape.assert_not_called()

    def test_request_validation(self):
        for changes in (dict(competitor_urls=[]), dict(competitor_urls=[URL] * 6),
                        dict(selling_price="-1"), dict(selling_price="NaN"),
                        dict(selling_price=True), dict(product_name=" "), dict(currency="EURO"),
                        dict(selling_price="1.1234567")):
            with self.subTest(changes=changes):
                self.assertEqual(self.post(**changes).status_code, 422)
        self.scrape.assert_not_called()

    def test_extract_contract_remains_numeric_without_sku(self):
        response = self.client.post("/api/prices/extract", json={"url": URL})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["price"], 19.99)
        self.assertNotIn("sku", response.json())
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
