"""Offline tests: all DNS, target-page requests, and provider calls are mocked."""
import os
import socket
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
from context.dev import APIConnectionError, APIStatusError, APITimeoutError
from fastapi.testclient import TestClient

from app.main import app
from offline_support import authorize_functional_tests
from app.services.context_client import scrape_product
from app.services.url_safety import UnsafeURL, check_redirects, public_destination

URL = "https://shop.example.com/products/mug"
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def page(**changes):
    product = dict(name="Travel Mug", brand="Demo", price=0.0,
                   currency="EUR", availability="in_stock")
    product.update(changes)
    return NS(url=URL, is_partial=False,
              product=NS(success=True, data=NS(is_product_page=True, product=NS(**product))))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        authorize_functional_tests(self)
        self.env = patch.dict(os.environ, {"CONTEXT_DEV_API_KEY": "test-placeholder"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.dns = patch("app.services.url_safety.socket.getaddrinfo", return_value=PUBLIC_DNS)
        self.dns.start()
        self.addCleanup(self.dns.stop)
        self.redirects = patch("app.services.extraction.check_redirects", return_value=URL)
        self.preflight = self.redirects.start()
        self.addCleanup(self.redirects.stop)
        self.sdk = patch("app.services.extraction.scrape_product", return_value=page())
        self.scrape = self.sdk.start()
        self.addCleanup(self.sdk.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def post(self, url=URL):
        return self.client.post("/api/prices/extract", json={"url": url})

    def test_success_and_zero_price(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["product_name"], "Travel Mug")
        self.assertEqual(data["price"], 0)
        self.assertEqual(data["source_url"], URL)
        self.assertIsNotNone(datetime.fromisoformat(data["observed_at"]).tzinfo)

    def test_unknown_fields_are_null_and_partial(self):
        self.scrape.return_value = page(brand=None, price=None, availability=None)
        data = self.post().json()
        self.assertEqual(data["status"], "partial")
        for field in ("brand", "price", "availability"):
            self.assertIsNone(data[field])

    def test_provider_partial_flag(self):
        self.scrape.return_value.is_partial = True
        self.assertEqual(self.post().json()["status"], "partial")

    def test_invalid_price_becomes_unknown(self):
        for price in (-1, float("nan"), float("inf"), True, "19.99"):
            with self.subTest(price=price):
                self.scrape.return_value = page(price=price)
                data = self.post().json()
                self.assertEqual(data["status"], "partial")
                self.assertIsNone(data["price"])

    def test_non_product(self):
        self.scrape.return_value.product.data = NS(is_product_page=False, product=None)
        response = self.post()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["status"], "failure")
        self.assertIn("not a product", response.json()["error"])

    def test_empty_and_failed_output(self):
        for output in (None, NS(success=False, data=None), NS(success=True, data=None),
                       NS(success=True, data=NS(is_product_page=True, product=None))):
            with self.subTest(output=output):
                self.scrape.return_value.product = output
                response = self.post()
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["status"], "failure")

    def test_no_usable_fields(self):
        self.scrape.return_value = page(name=" ", brand=None, price=None, currency=None, availability=None)
        self.assertEqual(self.post().status_code, 502)

    def test_malformed_provider_output(self):
        for output in (NS(), NS(success=True, data=NS()),
                       NS(success=True, data=NS(is_product_page=True))):
            with self.subTest(output=output):
                self.scrape.return_value.product = output
                self.assertEqual(self.post().status_code, 502)

    def test_request_validation(self):
        for url in ("not-url", "http://example.com/p", "ftp://example.com/p",
                    "https://user:password@example.com/p", "https://example.com:8443/p"):
            with self.subTest(url=url):
                self.assertEqual(self.post(url).status_code, 422)
        self.assertEqual(self.client.post("/api/prices/extract", json={}).status_code, 422)
        self.scrape.assert_not_called()

    def test_unsafe_preflight(self):
        self.preflight.side_effect = UnsafeURL()
        self.assertEqual(self.post().status_code, 400)
        self.scrape.assert_not_called()

    def test_unsafe_provider_redirect(self):
        self.scrape.return_value.url = "https://127.0.0.1/admin"
        with patch("app.services.url_safety.socket.getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ]):
            response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(response.json()["product_name"])

    def test_missing_key(self):
        with patch.dict(os.environ, {"CONTEXT_DEV_API_KEY": ""}):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.preflight.assert_not_called()
        self.scrape.assert_not_called()

    def test_timeout_and_connection_error_are_sanitized(self):
        request = httpx.Request("POST", "https://api.context.dev/v1/web/scrape")
        for error, expected in [(APITimeoutError(request=request), 504),
                                (APIConnectionError(message="secret-provider-detail", request=request), 502),
                                (httpx.ConnectError("secret-provider-detail"), 502)]:
            self.scrape.side_effect = error
            response = self.post()
            self.assertEqual(response.status_code, expected)
            self.assertNotIn("secret-provider-detail", response.text)
            self.assertNotIn("test-placeholder", response.text)

    def test_provider_status_errors(self):
        for status, expected in [(401, 503), (403, 503), (429, 503), (408, 504), (500, 502)]:
            self.scrape.side_effect = APIStatusError("secret-provider-detail", response=httpx.Response(
                status, request=httpx.Request("POST", "https://api.context.dev/v1/web/scrape")), body=None)
            response = self.post()
            self.assertEqual(response.status_code, expected)
            self.assertNotIn("secret-provider-detail", response.text)

    def test_original_routes_and_cors(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        for origin in ("http://localhost:3000", "http://localhost:5173"):
            response = self.client.options("/api/prices/extract", headers={
                "Origin": origin, "Access-Control-Request-Method": "POST"})
            self.assertEqual(response.headers["access-control-allow-origin"], origin)


class URLSafetyTests(unittest.TestCase):
    def test_ip_literals_do_not_depend_on_dns(self):
        with patch("app.services.url_safety.socket.getaddrinfo", return_value=PUBLIC_DNS) as dns:
            for url in ("https://127.0.0.1/p", "https://[::1]/p", "https://localhost./p"):
                with self.assertRaises(UnsafeURL):
                    public_destination(url)
            dns.assert_not_called()

    @patch("app.services.url_safety.httpx.Client")
    def test_dns_changes_on_next_redirect_are_rejected(self, client_class):
        client = client_class.return_value.__enter__.return_value
        client.stream.return_value.__enter__.return_value = httpx.Response(302, headers={"location": "/next"})
        private_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        with patch("app.services.url_safety.socket.getaddrinfo", side_effect=[PUBLIC_DNS, private_dns]):
            with self.assertRaises(UnsafeURL):
                check_redirects(URL)
        self.assertEqual(client.stream.call_count, 1)

    def test_private_reserved_and_mixed_dns_rejected(self):
        for address in ("127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254",
                        "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1"):
            with self.subTest(address=address), patch("app.services.url_safety.socket.getaddrinfo", return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
            ]):
                with self.assertRaises(UnsafeURL):
                    public_destination(URL)
        with patch("app.services.url_safety.socket.getaddrinfo", return_value=PUBLIC_DNS + [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))
        ]):
            with self.assertRaises(UnsafeURL):
                public_destination(URL)

    def test_local_names_and_dns_errors(self):
        for url in ("https://localhost/p", "https://foo.local/p", "https://server/p", "https://foo.internal/p"):
            with self.assertRaises(UnsafeURL):
                public_destination(url)
        with patch("app.services.url_safety.socket.getaddrinfo", side_effect=socket.gaierror()):
            with self.assertRaises(UnsafeURL):
                public_destination(URL)

    @patch("app.services.url_safety.socket.getaddrinfo", return_value=PUBLIC_DNS)
    @patch("app.services.url_safety.httpx.Client")
    def test_safe_relative_redirect_and_pinned_connection(self, client_class, dns):
        client = client_class.return_value.__enter__.return_value
        client.stream.return_value.__enter__.side_effect = [
            httpx.Response(302, headers={"location": "/new-product"}), httpx.Response(200)]
        self.assertEqual(check_redirects(URL), "https://shop.example.com/new-product")
        args, kwargs = client.stream.call_args
        self.assertEqual(args[1].host, "93.184.216.34")
        self.assertEqual(kwargs["extensions"]["sni_hostname"], "shop.example.com")

    @patch("app.services.url_safety.socket.getaddrinfo", return_value=PUBLIC_DNS)
    @patch("app.services.url_safety.httpx.Client")
    def test_unsafe_redirect_not_followed(self, client_class, dns):
        client = client_class.return_value.__enter__.return_value
        for location in ("http://example.com/p", "https://localhost/p", "https://admin.internal/p"):
            client.stream.reset_mock()
            client.stream.return_value.__enter__.return_value = httpx.Response(302, headers={"location": location})
            with self.assertRaises(UnsafeURL):
                check_redirects(URL)
            self.assertEqual(client.stream.call_count, 1)

    @patch("app.services.url_safety.socket.getaddrinfo", return_value=PUBLIC_DNS)
    @patch("app.services.url_safety.httpx.Client")
    def test_redirect_loop_and_missing_location(self, client_class, dns):
        client = client_class.return_value.__enter__.return_value
        for headers in ({"location": URL}, {}):
            client.stream.return_value.__enter__.return_value = httpx.Response(302, headers=headers)
            with self.assertRaises(UnsafeURL):
                check_redirects(URL)


class SDKTests(unittest.TestCase):
    @patch.dict(os.environ, {"CONTEXT_DEV_API_KEY": "test-placeholder"})
    @patch("app.services.context_client.ContextDev")
    def test_sdk_configuration(self, factory):
        scrape_product(URL)
        self.assertEqual(factory.call_args.kwargs["timeout"], 60.0)
        self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
        kwargs = factory.return_value.__enter__.return_value.web.scrape.call_args.kwargs
        self.assertEqual(kwargs["max_age_ms"], 0)
        self.assertEqual(kwargs["formats"], {"product": True})
        self.assertEqual(kwargs["zdr"], "disabled")


if __name__ == "__main__":
    unittest.main()
