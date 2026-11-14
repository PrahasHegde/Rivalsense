"""HTTP-level tests against mocked Supabase Auth/PostgREST, not a live project."""
import json
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from postgrest import SyncPostgrestClient
from app.core.auth import UserDatabase
from app.services.database import Repository
from app.main import app
from app.services.extraction import ProductObservation
from app.services.history import detect_change, observation_values, record_observation

USER_A, USER_B, PRODUCT, LISTING = [str(uuid4()) for _ in range(4)]
URL = "https://shop.example.com/mug"
NOW = "2026-11-14T12:00:00+00:00"
LATER = "2026-11-14T13:00:00+00:00"


def product():
    return dict(id=PRODUCT, user_id=USER_A, name="Acme Mug M-100", brand="Acme", sku="M-100",
                model_number="M-100", selling_price="120.00", cost_price=None, currency="EUR", created_at=NOW)


def listing():
    return dict(id=LISTING, user_id=USER_A, product_id=PRODUCT, competitor_name="Shop", product_url=URL,
                is_active=True, created_at=NOW)


def raw():
    return ProductObservation(status="success", product_name="Acme Mug M-100", brand="Acme", sku="M-100",
                              price=Decimal("110.00"), currency="EUR", availability="in_stock",
                              source_url=URL, observed_at=datetime.fromisoformat(LATER))


def observation(price="100.00", **changes):
    values = dict(id=str(uuid4()), user_id=USER_A, listing_id=LISTING, price=price, currency="EUR",
                  availability="in_stock", source_url=URL, extraction_status="success", observed_at=NOW,
                  matching_status="confirmed")
    values.update(changes)
    return values


class TrackingHTTPTests(unittest.TestCase):
    def setUp(self):
        self.data = {"products": [product()], "competitor_listings": [listing()],
                     "price_observations": [], "alerts": []}
        self.requests = []
        self.auth_status = 200
        self.db_status = 200
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        env = patch.dict(os.environ, {"SUPABASE_URL": "https://project.example.com",
                                     "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test_placeholder",
                                     "SUPABASE_PRICE_HISTORY_RPC_ENABLED": "false",
                                     "PRICE_CHANGE_THRESHOLD_PERCENT": "5"})
        env.start()
        self.addCleanup(env.stop)
        real_client = httpx.Client
        factory = patch("app.core.auth.httpx.Client", side_effect=lambda **kwargs:
                        real_client(transport=httpx.MockTransport(self.respond), **kwargs))
        factory.start()
        self.addCleanup(factory.stop)
        self.extraction = patch("app.services.history.extract_product", return_value=(raw(), 200))
        self.extract = self.extraction.start()
        self.addCleanup(self.extraction.stop)

    def respond(self, request):
        self.requests.append(request)
        token = request.headers.get("authorization", "")
        owner = {"Bearer token-a": USER_A, "Bearer token-b": USER_B}.get(token)
        if request.url.path == "/auth/v1/user":
            status = self.auth_status if owner else 401
            return httpx.Response(status, json={"id": owner} if status == 200 else {"message": "private auth error"})
        if self.db_status != 200:
            return httpx.Response(self.db_status, json={"code": "PGRST204", "message": "private database error"})
        table = request.url.path.rsplit("/", 1)[-1]
        if table not in self.data:
            raise AssertionError("Unexpected network operation")
        # This models ownership enforcement, not proof of the deployed SQL policies.
        if request.method == "POST":
            values = json.loads(request.content)
            assert values["user_id"] == owner
            if any(row["id"] == values.get("id") for row in self.data[table]):
                return httpx.Response(409, json={"code": "23505", "message": "duplicate"})
            row = {"id": str(uuid4()), "created_at": NOW, **values}
            if table == "competitor_listings":
                row["is_active"] = True
            self.data[table].append(row)
            return httpx.Response(201, json=[row])
        assert request.url.params.get("user_id") == "eq." + owner
        rows = [row for row in self.data[table] if row["user_id"] == owner]
        for key, value in request.url.params.multi_items():
            if value.startswith("eq."):
                rows = [row for row in rows if str(row.get(key)) == value[3:]]
        ordering = request.url.params.get("order", "")
        if ordering:
            columns = [item.split(".")[0] for item in ordering.split(",")]
            rows.sort(key=lambda row: tuple(row.get(column, "") for column in columns), reverse=True)
        start = int(request.url.params.get("offset", "0"))
        limit = int(request.url.params.get("limit", "100"))
        return httpx.Response(200, json=rows[start:start + limit])

    def call(self, method, path, user="a", **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = "Bearer token-" + user
        return self.client.request(method, path, headers=headers, **kwargs)

    def test_auth_required_invalid_expired_and_auth_outage(self):
        self.assertEqual(self.client.get("/api/products").status_code, 401)
        self.assertEqual(self.call("GET", "/api/products", user="invalid").status_code, 401)
        self.auth_status = 401
        self.assertEqual(self.call("GET", "/api/products").status_code, 401)
        self.auth_status = 503
        response = self.call("GET", "/api/products")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private auth error", response.text)
        self.assertFalse(any("rest/v1" in str(request.url) for request in self.requests))

    def test_user_token_forwarded_and_no_cross_user_state(self):
        a = self.call("GET", "/api/products")
        b = self.call("GET", "/api/products", user="b")
        self.assertEqual(len(a.json()), 1)
        self.assertEqual(b.json(), [])
        database_requests = [request for request in self.requests if "rest/v1" in str(request.url)]
        self.assertEqual([request.headers["Authorization"] for request in database_requests],
                         ["Bearer token-a", "Bearer token-b"])
        self.assertEqual(database_requests[0].headers["apikey"], "sb_publishable_test_placeholder")
        self.assertNotIn("token-a", a.text)
        self.assertNotIn("sb_publishable", a.text)

    def test_cross_user_product_listing_history_and_observation_are_hidden(self):
        for method, path, kwargs in (
            ("GET", f"/api/products/{PRODUCT}", {}),
            ("GET", f"/api/products/{PRODUCT}/competitors", {}),
            ("POST", f"/api/products/{PRODUCT}/competitors", {"json": {"competitor_name": "Shop", "product_url": URL}}),
            ("GET", f"/api/competitors/{LISTING}/observations", {}),
            ("POST", f"/api/competitors/{LISTING}/observations", {"headers": {"Idempotency-Key": str(uuid4())}}),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.call(method, path, user="b", **kwargs).status_code, 404)
        self.extract.assert_not_called()

    def test_create_product_decimal_and_owner_cannot_be_spoofed(self):
        body = dict(name="New Mug", selling_price="19.99", currency="EUR")
        response = self.call("POST", "/api/products", json=body)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["selling_price"], "19.99")
        self.assertEqual(response.json()["user_id"], USER_A)
        self.assertEqual(self.call("POST", "/api/products", json={**body, "user_id": USER_B}).status_code, 422)
        self.assertEqual(self.call("POST", "/api/products", json={**body, "selling_price": "1.001"}).status_code, 422)

    def test_add_and_list_competitor(self):
        with patch("app.api.tracking.public_destination", return_value=(URL, "93.184.216.34")):
            response = self.call("POST", f"/api/products/{PRODUCT}/competitors",
                                 json={"competitor_name": "Shop 2", "product_url": URL})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["product_id"], PRODUCT)
        self.assertEqual(len(self.call("GET", f"/api/products/{PRODUCT}/competitors").json()), 2)

    def test_save_append_history_and_replay_without_second_extraction(self):
        path = f"/api/competitors/{LISTING}/observations"
        key = str(uuid4())
        first = self.call("POST", path, headers={"Idempotency-Key": key})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["alert_status"], "migration_required")
        second = self.call("POST", path, headers={"Idempotency-Key": key})
        self.assertTrue(second.json()["replayed"])
        self.extract.assert_called_once()
        self.call("POST", path, headers={"Idempotency-Key": str(uuid4())})
        history = self.call("GET", path).json()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["price"], "110.00")
        self.assertEqual(history[0]["matching_status"], "needs_review")
        self.assertEqual(self.data["alerts"], [])

    def test_failed_extraction_is_saved_without_invented_price(self):
        self.extract.return_value = (ProductObservation(status="failure", source_url=URL,
            observed_at=datetime.now(timezone.utc), error="Extraction timed out"), 504)
        response = self.call("POST", f"/api/competitors/{LISTING}/observations",
                             headers={"Idempotency-Key": str(uuid4())})
        data = response.json()
        self.assertEqual(data["observation"]["extraction_status"], "failure")
        self.assertIsNone(data["observation"]["price"])
        self.assertEqual(data["observation"]["extraction_error"], "Extraction timed out")
        self.assertNotIn("extraction_error", self.data["price_observations"][0])

    def test_missing_idempotency_header_no_extraction(self):
        self.assertEqual(self.call("POST", f"/api/competitors/{LISTING}/observations").status_code, 422)
        self.extract.assert_not_called()

    def test_database_errors_are_sanitized(self):
        self.db_status = 500
        response = self.call("GET", "/api/products")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private database error", response.text)

    def test_pagination_and_alert_user_scope(self):
        self.data["products"].append({**product(), "id": str(uuid4())})
        self.assertEqual(len(self.call("GET", "/api/products?limit=1&offset=1").json()), 1)
        self.assertEqual(self.call("GET", "/api/products?limit=101").status_code, 422)
        self.assertEqual(self.call("GET", "/api/alerts", user="b").json(), [])


class ChangeTests(unittest.TestCase):
    def current(self, price="110.00", **changes):
        return observation(price, observed_at=LATER, **changes)

    def test_exact_threshold_and_downward_changes(self):
        result = detect_change(observation(), self.current(), Decimal(5))
        self.assertEqual(result.price_difference, Decimal("10.00"))
        self.assertEqual(result.percentage_change, Decimal(10))
        self.assertTrue(result.exceeds_threshold)
        self.assertFalse(detect_change(observation(), self.current("105.00"), Decimal(5)).exceeds_threshold)
        result = detect_change(observation(), self.current("80.00"), Decimal(5))
        self.assertEqual(result.percentage_change, Decimal(-20))
        self.assertTrue(result.exceeds_threshold)

    def test_no_baseline_zero_unchanged_invalid_or_out_of_order(self):
        self.assertEqual(detect_change(None, self.current(), Decimal(5)).status, "no_baseline")
        self.assertEqual(detect_change(observation("0"), self.current(), Decimal(5)).status, "zero_baseline")
        self.assertEqual(detect_change(observation(), self.current("100"), Decimal(5)).status, "unchanged")
        for changes in (dict(currency="USD"), dict(matching_status="needs_review"),
                        dict(extraction_status="failure"), dict(price=None)):
            current = self.current()
            current.update(changes)
            self.assertEqual(detect_change(observation(), current, Decimal(5)).status, "not_comparable")
        self.assertEqual(detect_change(observation(observed_at=LATER), self.current(), Decimal(5)).status, "out_of_order")

    def test_numeric_schema_precision_is_not_silently_rounded(self):
        extracted = raw()
        extracted.price = Decimal("1.999")
        saved = observation_values(extracted, "confirmed", uuid4())
        self.assertIsNone(saved["price"])
        self.assertIn("numeric(14,2)", saved["extraction_error"])
        self.assertEqual(saved["extracted_product"]["price"], "1.999")

    @patch.dict(os.environ, {"SUPABASE_PRICE_HISTORY_RPC_ENABLED": "true", "PRICE_CHANGE_THRESHOLD_PERCENT": "5"})
    @patch("app.services.history.extract_product", return_value=(raw(), 200))
    def test_atomic_alert_retry_reuses_extraction(self, extract):
        repository = MagicMock()
        repository.get.side_effect = [listing(), product()]
        repository.existing_observation.return_value = None
        repository.previous_valid.side_effect = [observation(), observation("101")]
        repository.record_atomic.side_effect = [None, {"observation": self.current(), "alert": None}]
        result = record_observation(repository, LISTING, uuid4())
        self.assertTrue(result.change.exceeds_threshold)
        extract.assert_called_once()
        self.assertEqual(repository.record_atomic.call_count, 2)
        payload = repository.record_atomic.call_args.args[3]
        self.assertEqual(payload["old_price"], "101")
        self.assertEqual(payload["new_price"], "110.00")

    @patch.dict(os.environ, {"SUPABASE_PRICE_HISTORY_RPC_ENABLED": "true", "PRICE_CHANGE_THRESHOLD_PERCENT": "5"})
    @patch("app.services.history.extract_product", return_value=(raw(), 200))
    def test_bounded_atomic_contention_does_not_repeat_provider_calls(self, extract):
        repository = MagicMock()
        repository.get.side_effect = [listing(), product()]
        repository.existing_observation.return_value = None
        repository.previous_valid.return_value = observation()
        repository.record_atomic.return_value = None
        with self.assertRaises(HTTPException) as caught:
            record_observation(repository, LISTING, uuid4())
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(repository.record_atomic.call_count, 3)
        extract.assert_called_once()

    @patch.dict(os.environ, {"SUPABASE_PRICE_HISTORY_RPC_ENABLED": "true", "PRICE_CHANGE_THRESHOLD_PERCENT": "5"})
    @patch("app.services.history.extract_product", return_value=(raw(), 200))
    def test_completed_atomic_alert_and_duplicate_replay(self, extract):
        repository = MagicMock()
        repository.get.side_effect = [listing(), product(), listing(), product()]
        saved = self.current()
        saved_alert = dict(id=str(uuid4()), user_id=USER_A, product_id=PRODUCT,
                           event_type="competitor_price_change", severity="medium", title="Price change",
                           old_price="100.00", new_price="110.00", currency="EUR", status="unread", created_at=LATER)
        repository.existing_observation.side_effect = [None, saved]
        repository.previous_valid.return_value = observation()
        repository.record_atomic.return_value = {"observation": saved, "alert": saved_alert, "replayed": False}
        key = uuid4()
        first = record_observation(repository, LISTING, key)
        second = record_observation(repository, LISTING, key)
        self.assertEqual(first.alert_status, "created")
        self.assertEqual(first.alert.new_price, Decimal("110.00"))
        self.assertTrue(second.replayed)
        repository.record_atomic.assert_called_once()
        extract.assert_called_once()


class PostgrestContractTests(unittest.TestCase):
    def test_rpc_json_serialization_and_response(self):
        captured = []

        def respond(request):
            captured.append(request)
            return httpx.Response(200, json={"observation": observation(), "alert": None, "replayed": False})

        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            with SyncPostgrestClient("https://project.example.com/rest/v1", http_client=transport,
                                     headers={"Authorization": "Bearer token-a"}, retry_enabled=False) as client:
                repository = Repository(UserDatabase(USER_A, client))
                result = repository.record_atomic(LISTING, {"id": str(uuid4()), "price": "110.00"}, None, None)
        self.assertIsInstance(result, dict)
        request = captured[0]
        self.assertEqual(request.url.path, "/rest/v1/rpc/rivalsense_record_observation")
        body = json.loads(request.content)
        self.assertEqual(body["p_observation"]["price"], "110.00")
        self.assertIsNone(body["p_previous_id"])
        self.assertNotIn("token-a", request.content.decode())

    def test_previous_query_skips_unconfirmed_failed_and_null_prices(self):
        captured = []

        def respond(request):
            captured.append(request)
            return httpx.Response(200, json=[])

        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            with SyncPostgrestClient("https://project.example.com/rest/v1", http_client=transport, retry_enabled=False) as client:
                self.assertIsNone(Repository(UserDatabase(USER_A, client)).previous_valid(LISTING, "EUR"))
        params = captured[0].url.params
        self.assertEqual(params["user_id"], "eq." + USER_A)
        self.assertEqual(params["listing_id"], "eq." + LISTING)
        self.assertEqual(params["currency"], "eq.EUR")
        self.assertEqual(params["matching_status"], "eq.confirmed")
        self.assertEqual(params["extraction_status"], "in.(success,partial)")
        self.assertEqual(params["price"], "not.is.null")

    def test_database_serialization_conflict_retries_only_at_service_level(self):
        def respond(request):
            return httpx.Response(409, json={"code": "40001", "message": "baseline changed"})

        with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
            with SyncPostgrestClient("https://project.example.com/rest/v1", http_client=transport, retry_enabled=False) as client:
                result = Repository(UserDatabase(USER_A, client)).record_atomic(LISTING, {}, None, None)
        self.assertIsNone(result)
