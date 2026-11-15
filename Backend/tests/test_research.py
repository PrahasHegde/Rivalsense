"""Research HTTP/SDK contracts, evidence handling, and independent read quotas."""
from contextlib import nullcontext
from types import SimpleNamespace as NS
import json
import os
import unittest
from unittest.mock import patch, MagicMock
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from context.dev import ContextDev, APIStatusError, APITimeoutError
from app.main import app
from app.core.auth import UserDatabase, get_user_database
from app.services.context_client import research_question
from app.services.research import ask, save_optional
from app.services.read_budget import LocalReadBudget, reading_budget
from offline_support import USER_A

URL = "https://example.com/report"
def response(**changes):
    value = dict(json_content={"answer": "Supported result", "keywords": ["topic"],
        "facts": [{"label": "Finding", "value": "A fact", "source_url": URL}],
        "uncertainties": ["Data may be incomplete"]}, sources=[URL], partial=False)
    return NS(**(value | changes))

class ResearchTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_user_database] = lambda: UserDatabase(USER_A, None)
        self.addCleanup(lambda: app.dependency_overrides.pop(get_user_database, None))
        budget = patch("app.api.research.reading_budget", return_value=nullcontext())
        budget.start(); self.addCleanup(budget.stop)
        provider = patch("app.services.research.research_question", return_value=response())
        self.provider = provider.start(); self.addCleanup(provider.stop)
        env = patch.dict(os.environ, {"RESEARCH_HISTORY_ENABLED": "false"})
        env.start(); self.addCleanup(env.stop)
        self.client = TestClient(app); self.addCleanup(self.client.close)

    def test_actual_question_response_contract_and_sources(self):
        result = self.client.post("/api/ai/ask", json={"question": "  Research this topic?  "})
        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertEqual(data["question"], "Research this topic?")
        self.assertEqual(data["sources"][0]["url"], URL)
        self.assertIsNone(data["sources"][0]["publisher"])
        self.assertIsNone(data["sources"][0]["published_at"])
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["persistence"], "not_configured")
        self.assertIn("retrieved_at", data)

    def test_empty_missing_or_unsafe_sources_never_make_a_completed_answer(self):
        for sources in ([], ["javascript:alert(1)"], ["http://127.0.0.1/private"], ["https://user:password@example.com"]):
            self.provider.return_value = response(sources=sources)
            data = self.client.post("/api/ai/ask", json={"question": "A real question"}).json()
            self.assertEqual(data["status"], "insufficient_evidence")
            self.assertEqual(data["sources"], [])
            self.assertNotEqual(data["answer"], "Supported result")

    def test_partial_and_fact_url_validation(self):
        value = response(partial=True)
        value.json_content["facts"][0]["source_url"] = "https://invented.example/fake"
        self.provider.return_value = value
        data = self.client.post("/api/ai/ask", json={"question": "A real question"}).json()
        self.assertEqual(data["status"], "partial")
        self.assertIsNone(data["research_data"]["facts"][0]["source_url"])

    def test_request_validation_and_optional_history_without_database(self):
        for body in ({"question": "  "}, {"question": "x"*2001}, {"question": "Valid question", "user_id": USER_A}):
            self.assertEqual(self.client.post("/api/ai/ask", json=body).status_code, 422)
        self.assertEqual(self.client.get("/api/ai/history").json(), {"items": [], "status": "not_configured"})

    def test_persistence_outage_does_not_discard_answer(self):
        result = ask("A real question")
        repository = MagicMock()
        repository.insert.side_effect = HTTPException(503, "database failed")
        with patch.dict(os.environ, {"RESEARCH_HISTORY_ENABLED": "true"}):
            saved = save_optional(repository, result)
        self.assertEqual(saved.answer, result.answer)
        self.assertEqual(saved.persistence, "unavailable")
        self.assertEqual(repository.insert.call_args.args[0], "ai_responses")

    def test_auth_is_required_before_provider(self):
        app.dependency_overrides.pop(get_user_database)
        self.assertEqual(self.client.post("/api/ai/ask", json={"question": "A real question"}).status_code, 401)
        self.provider.assert_not_called()

    def test_actual_development_origin_cors_preflight(self):
        result = self.client.options("/api/ai/ask", headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers.get("access-control-allow-origin"), "http://127.0.0.1:5173")

    def test_sanitized_provider_auth_and_quota_errors(self):
        request = httpx.Request("POST", "https://api.context.dev/v1/web/answers")
        for code, status in ((401, 503), (403, 503), (429, 503), (500, 502)):
            self.provider.side_effect = APIStatusError("private provider error", response=httpx.Response(code, request=request), body={})
            data = self.client.post("/api/ai/ask", json={"question": "A real question"})
            self.assertEqual(data.status_code, status)
            self.assertNotIn("private provider error", data.text)

    def test_timeout_and_bad_response(self):
        self.provider.side_effect = APITimeoutError(request=httpx.Request("POST", "https://api.context.dev"))
        self.assertEqual(self.client.post("/api/ai/ask", json={"question": "A real question"}).status_code, 504)
        self.provider.side_effect = None; self.provider.return_value = response(json_content=None)
        self.assertEqual(self.client.post("/api/ai/ask", json={"question": "A real question"}).status_code, 502)

class AnswersSDKTests(unittest.TestCase):
    @patch.dict(os.environ, {"CONTEXT_DEV_API_KEY": "test-only-placeholder"})
    def test_real_sdk_request_serialization(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"json_content": {"answer": "Sourced answer"}, "sources": [URL], "request_id": "test-only", "partial": False})
        with ContextDev(api_key="test-only-placeholder", http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
            with patch("app.services.context_client.ContextDev", return_value=client):
                result = research_question("Who founded Microsoft?")
        self.assertEqual(requests[0].url.path, "/v1/web/answers")
        body = json.loads(requests[0].content)
        self.assertEqual(body["mode"], "fast")
        self.assertEqual(body["timeoutOpts"]["behavior"], "return-partial")
        self.assertIn("json_format", body)
        self.assertEqual(result.sources, [URL])

class ReadBudgetTests(unittest.TestCase):
    @patch.dict(os.environ, {"RIVALSENSE_READS_PER_MINUTE": "2", "RIVALSENSE_GLOBAL_READS_PER_MINUTE": "3", "RIVALSENSE_READ_CONCURRENCY": "1"})
    def test_units_concurrency_failures_and_expiry(self):
        clock = [0]
        limiter = LocalReadBudget(lambda: clock[0])
        with limiter.reserve("a", 1):
            with self.assertRaises(HTTPException) as error:
                with limiter.reserve("a", 1): pass
            self.assertEqual(error.exception.status_code, 429)
        with self.assertRaises(ValueError):
            with limiter.reserve("a", 1): raise ValueError("provider failed")
        with self.assertRaises(HTTPException):
            with limiter.reserve("a", 1): pass
        with limiter.reserve("b", 1): pass
        with self.assertRaises(HTTPException):
            with limiter.reserve("c", 1): pass
        clock[0] = 61
        with limiter.reserve("a", 2): pass

    def test_database_mode_remains_default_and_never_silently_falls_back(self):
        with patch.dict(os.environ, {"RIVALSENSE_READ_BUDGET": "database"}), patch("app.services.read_budget.extraction_budget", side_effect=HTTPException(503, "unavailable")):
            with self.assertRaises(HTTPException):
                with reading_budget(MagicMock()): pass
