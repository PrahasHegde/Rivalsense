"""Actual HTTP auth/owner-filter and signed PostgREST wire contracts, all offline."""
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from postgrest import SyncPostgrestClient
from app.main import app
from app.core.auth import UserDatabase
from app.services.database import Repository
from offline_support import USER_A, USER_B, PRODUCT, LISTING, URL, product, listing, raw, observation


class TrackingHTTPTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.auth_status = 200
        self.db_status = 200
        self.rows = {"products": [product()], "competitor_listings": [listing()], "price_observations": [], "alerts": []}
        env = patch.dict(os.environ, {"SUPABASE_URL": "https://project.example.com",
                                     "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test_placeholder"})
        env.start()
        self.addCleanup(env.stop)
        real_client = httpx.Client
        transport = patch("app.core.auth.httpx.Client", side_effect=lambda **kw:
                          real_client(transport=httpx.MockTransport(self.respond), **kw))
        transport.start()
        self.addCleanup(transport.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def respond(self, request):
        self.requests.append(request)
        owner = {"Bearer token-a": USER_A, "Bearer token-b": USER_B}.get(request.headers.get("authorization"))
        if request.url.path == "/auth/v1/user":
            status = self.auth_status if owner else 401
            return httpx.Response(status, json={"id": owner} if status == 200 else {"message": "private auth error"})
        if self.db_status != 200:
            return httpx.Response(self.db_status, json={"code": "PGRST204", "message": "private database error"})
        table = request.url.path.rsplit("/", 1)[-1]
        rows = self.rows[table]
        if request.method == "POST":
            values = json.loads(request.content)
            assert values["user_id"] == owner
            row = {"id": str(uuid4()), "created_at": product()["created_at"], **values}
            if table == "competitor_listings":
                row["is_active"] = True
            rows.append(row)
            return httpx.Response(201, json=[row])
        assert request.url.params["user_id"] == "eq." + owner
        selected = [r for r in rows if r["user_id"] == owner]
        for key, value in request.url.params.multi_items():
            if value.startswith("eq."):
                selected = [r for r in selected if str(r.get(key)) == value[3:]]
        if request.method == "PATCH":
            for row in selected:
                row.update(json.loads(request.content))
        start = int(request.url.params.get("offset", 0))
        limit = int(request.url.params.get("limit", 100))
        return httpx.Response(200, json=selected[start:start+limit])

    def call(self, method, path, user="a", **kw):
        return self.client.request(method, path, headers={"Authorization": "Bearer token-"+user}, **kw)

    def test_auth_and_outage_do_not_reach_database(self):
        self.assertEqual(self.client.get("/api/products").status_code, 401)
        self.assertEqual(self.call("GET", "/api/products", user="invalid").status_code, 401)
        self.auth_status = 503
        response = self.call("GET", "/api/products")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private auth error", response.text)
        self.assertFalse(any("/rest/" in str(r.url) for r in self.requests))

    def test_tokens_and_owner_filters_are_request_scoped(self):
        self.assertEqual(len(self.call("GET", "/api/products").json()), 1)
        self.assertEqual(self.call("GET", "/api/products", user="b").json(), [])
        requests = [r for r in self.requests if "/rest/" in str(r.url)]
        self.assertEqual([r.headers["authorization"] for r in requests], ["Bearer token-a", "Bearer token-b"])

    def test_cross_user_reads_and_archival_are_hidden(self):
        for method, path, kw in (
            ("GET", f"/api/products/{PRODUCT}", {}),
            ("GET", f"/api/competitors/{LISTING}/observations", {}),
            ("PATCH", f"/api/products/{PRODUCT}", {"json": {"is_archived": True}}),
            ("PATCH", f"/api/competitors/{LISTING}", {"json": {"is_active": False}}),
        ):
            self.assertEqual(self.call(method, path, user="b", **kw).status_code, 404)

    def test_product_creation_and_spoofing(self):
        body = dict(name="New Mug", selling_price="19.99", currency="EUR")
        result = self.call("POST", "/api/products", json=body)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()["selling_price"], "19.99")
        self.assertEqual(result.json()["user_id"], USER_A)
        for change in ({"user_id": USER_B}, {"selling_price": "1.001"}, {"selling_price": True}):
            self.assertEqual(self.call("POST", "/api/products", json=body|change).status_code, 422)

    def test_identity_updates_rejected_and_archival_keeps_history(self):
        self.rows["price_observations"].append(observation())
        self.assertEqual(self.call("PATCH", f"/api/products/{PRODUCT}", json={"name": "Other"}).status_code, 422)
        self.assertEqual(self.call("PATCH", f"/api/competitors/{LISTING}", json={"product_url": URL+"/new"}).status_code, 422)
        self.assertTrue(self.call("PATCH", f"/api/products/{PRODUCT}", json={"is_archived": True}).json()["is_archived"])
        self.assertFalse(self.call("PATCH", f"/api/competitors/{LISTING}", json={"is_active": False}).json()["is_active"])
        self.assertEqual(len(self.call("GET", f"/api/competitors/{LISTING}/observations").json()), 1)

    def test_listing_and_pagination(self):
        with patch("app.api.tracking.public_destination", return_value=(URL, "93.184.216.34")):
            response = self.call("POST", f"/api/products/{PRODUCT}/competitors",
                                 json={"competitor_name": "Shop", "product_url": URL})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.call("GET", "/api/products?limit=101").status_code, 422)

    def test_database_error_is_sanitized(self):
        self.db_status = 500
        response = self.call("GET", "/api/products")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private database error", response.text)

    def test_missing_idempotency_header(self):
        self.assertEqual(self.call("POST", f"/api/competitors/{LISTING}/observations").status_code, 422)


class PostgrestContractTests(unittest.TestCase):
    def test_all_signed_rpc_names_and_parameters(self):
        captured = []
        def respond(request):
            captured.append(request)
            return httpx.Response(200, json={"state": "ready"})
        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            with SyncPostgrestClient("https://project.example.com/rest/v1", http_client=transport, retry_enabled=False) as client:
                repository = Repository(UserDatabase(USER_A, client))
                for name in ("rivalsense_record_verified_capture", "rivalsense_capture_receipt", "rivalsense_rate_limit"):
                    self.assertEqual(repository.signed_rpc(name, "exact UTF-8: ä", "signature"), {"state": "ready"})
                    self.assertEqual(captured[-1].url.path, "/rest/v1/rpc/"+name)
                    self.assertEqual(json.loads(captured[-1].content), {"p_payload": "exact UTF-8: ä", "p_signature": "signature"})
                with self.assertRaises(ValueError):
                    repository.signed_rpc("rivalsense_record_observation", "", "")

    def test_failures_are_sanitized_and_not_automatically_retried(self):
        for code, status in (("23505", 409), ("22023", 409), ("42501", 403), ("40001", 503), ("unknown", 503)):
            requests = []
            def respond(request):
                requests.append(request)
                return httpx.Response(400, json={"code": code, "message": "private details"})
            with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
                with SyncPostgrestClient("https://project.example.com/rest/v1", http_client=transport, retry_enabled=False) as client:
                    with self.assertRaises(HTTPException) as caught:
                        Repository(UserDatabase(USER_A, client)).signed_rpc("rivalsense_capture_receipt", "x", "y")
            self.assertEqual(caught.exception.status_code, status)
            self.assertNotIn("private details", caught.exception.detail)
            self.assertEqual(len(requests), 1)
