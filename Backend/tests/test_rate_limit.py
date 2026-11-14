"""HTTP auth gates and quota orchestration, using mocked Auth/PostgREST only."""
from contextlib import nullcontext
import os
import unittest
from unittest.mock import MagicMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.core.auth import UserDatabase, get_user_database
from app.services.rate_limit import extraction_budget
from offline_support import USER_A, URL, raw

SECRET = "test-only-secret-for-offline-tests-0000"


class RateLimitTests(unittest.TestCase):
    @patch.dict(os.environ, {"RIVALSENSE_RECORDING_SECRET": SECRET})
    def test_success_failure_and_release_commands(self):
        repo = MagicMock(user_id=USER_A)
        repo.signed_rpc.return_value = {"allowed": True}
        with extraction_budget(repo, units=3):
            pass
        import json
        commands = [json.loads(call.args[1]) for call in repo.signed_rpc.call_args_list]
        self.assertEqual(commands[0]["units"], 3)
        self.assertEqual(commands[0]["reservation_id"], commands[1]["reservation_id"])
        self.assertEqual([p["operation"] for p in commands], ["acquire", "release"])
        repo.reset_mock()
        with self.assertRaises(ValueError):
            with extraction_budget(repo):
                raise ValueError("provider failed")
        self.assertEqual(repo.signed_rpc.call_count, 2)

    @patch.dict(os.environ, {"RIVALSENSE_RECORDING_SECRET": SECRET})
    def test_quota_and_storage_outage_fail_closed(self):
        repo = MagicMock(user_id=USER_A)
        repo.signed_rpc.return_value = {"allowed": False, "retry_after": 123}
        with self.assertRaises(HTTPException) as caught:
            with extraction_budget(repo):
                self.fail("must not start extraction")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers["Retry-After"], "123")
        repo.signed_rpc.side_effect = HTTPException(503, "Database unavailable")
        with self.assertRaises(HTTPException) as caught:
            with extraction_budget(repo):
                self.fail("must fail closed")
        self.assertEqual(caught.exception.status_code, 503)

    @patch.dict(os.environ, {"RIVALSENSE_RECORDING_SECRET": SECRET})
    def test_release_outage_does_not_hide_success(self):
        repo = MagicMock(user_id=USER_A)
        repo.signed_rpc.side_effect = [{"allowed": True}, HTTPException(503, "outage")]
        with self.assertLogs("app.services.rate_limit", level="WARNING"):
            with extraction_budget(repo):
                pass

    def test_both_endpoints_reject_missing_and_invalid_tokens_before_provider(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "https://project.example.com",
                                    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_placeholder"}):
            real_client = httpx.Client
            with patch("app.core.auth.httpx.Client", side_effect=lambda **kw: real_client(
                    transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})), **kw)):
                with TestClient(app) as client, patch("app.api.prices.extract_product") as extract, patch("app.api.prices.compare_prices") as compare:
                    for path, body in (("/api/prices/extract", {"url": URL}), ("/api/prices/compare", {
                        "product_name": "Mug", "selling_price": "20", "currency": "EUR", "competitor_urls": [URL]})):
                        self.assertEqual(client.post(path, json=body).status_code, 401)
                        self.assertEqual(client.post(path, json=body, headers={"Authorization": "Bearer bad"}).status_code, 401)
                    extract.assert_not_called()
                    compare.assert_not_called()

    def test_comparison_charges_each_url_and_quota_denial_stops_provider(self):
        app.dependency_overrides[get_user_database] = lambda: UserDatabase(USER_A, None)
        self.addCleanup(lambda: app.dependency_overrides.pop(get_user_database, None))
        body = {"product_name": "Mug", "selling_price": "20", "currency": "EUR", "competitor_urls": [URL, URL+"/other"]}
        with TestClient(app) as client, patch("app.api.prices.extraction_budget", return_value=nullcontext()) as budget, patch("app.api.prices.compare_prices", return_value={}):
            # Response validation is irrelevant here; the quota reservation occurs before it.
            with self.assertRaises(Exception):
                client.post("/api/prices/compare", json=body)
            self.assertEqual(budget.call_args.kwargs["units"], 2)
        with TestClient(app) as client, patch("app.api.prices.extraction_budget", side_effect=HTTPException(429, "quota", headers={"Retry-After": "60"})), patch("app.api.prices.extract_product") as extract:
            response = client.post("/api/prices/extract", json={"url": URL})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["Retry-After"], "60")
            extract.assert_not_called()
