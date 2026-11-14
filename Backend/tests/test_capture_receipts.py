"""Backend orchestration tests. Receipt model is not a PostgreSQL engine."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from threading import Lock
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from app.services.history import record_observation
from app.services.capture_receipts import CaptureReceipts, require_receipt
from app.services.capture_attestation import verify_capture
from offline_support import USER_A, LISTING, product, listing, raw, observation

SECRET = "test-only-secret-for-offline-tests-0000"


def db_result():
    # Deliberately differs from old env threshold and price-derived outcome.
    return {"observation": observation("110.00"),
            "change": {"status": "changed", "threshold_percent": "17.25",
                       "exceeds_threshold": False, "price_difference": "10.00"},
            "alert_status": "disabled", "alert": None, "replayed": False}


class ReceiptModel:
    """Thread-safe fake of RPC storage, for observing backend protocol behavior."""
    def __init__(self):
        self.lock = Lock()
        self.receipts = {}
        self.calls = []
        self.fail_save = False
        self.fail_record = False
        self.expired = False
        self.indeterminate = False

    def execute(self, name, text, signature):
        assert verify_capture(text, signature, SECRET)
        p = json.loads(text)
        assert p["user_id"] == USER_A
        with self.lock:
            self.calls.append(name)
            if name == "rivalsense_capture_receipt":
                key = p["request_key"]
                r = self.receipts.get(key)
                if r and r["listing_id"] != p["listing_id"]:
                    raise HTTPException(409, "Conflicting listing")
                if r and r["state"] in ("ready", "completed"):
                    return deepcopy(r)
                if r and (self.expired or self.indeterminate):
                    r["state"] = "indeterminate"
                    return deepcopy(r)
                if p["operation"] == "claim":
                    if r:
                        return {"state": "busy"}
                    r = {"state": "extracting", "capture_event_id": str(uuid4()), "token": p["token"],
                         "listing": listing(), "product": product(), "listing_id": p["listing_id"]}
                    if self.indeterminate:
                        return {"state": "indeterminate"}
                    self.receipts[key] = r
                    return deepcopy(r)
                assert p["operation"] == "save" and p["token"] == r["token"]
                assert verify_capture(p["payload"], p["signature"], SECRET)
                r.update(state="ready", payload=p["payload"], signature=p["signature"])
                if self.fail_save:
                    self.fail_save = False
                    raise HTTPException(503, "Response lost after durable save")
                return deepcopy(r)
            assert name == "rivalsense_record_verified_capture"
            r = next(r for r in self.receipts.values() if r["capture_event_id"] == p["capture_event_id"])
            assert r["payload"] == text and r["signature"] == signature
            if r["state"] == "completed":
                return deepcopy(r["result"]) | {"replayed": True}
            r.update(state="completed", result=db_result())
            if self.fail_record:
                self.fail_record = False
                raise HTTPException(503, "Response lost after commit")
            return deepcopy(r["result"])


class CaptureReceiptTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"RIVALSENSE_RECORDING_ENABLED": "true", "RIVALSENSE_RECORDING_SECRET": SECRET,
                                     "PRICE_CHANGE_THRESHOLD_PERCENT": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.model = ReceiptModel()
        self.repo = MagicMock(user_id=USER_A)
        self.repo.get.return_value = listing()
        self.repo.signed_rpc.side_effect = self.model.execute
        extract = patch("app.services.history.extract_product", return_value=(raw(), 200))
        self.extract = extract.start()
        self.addCleanup(extract.stop)
        self.key = uuid4()

    def record(self):
        return record_observation(self.repo, LISTING, self.key)

    def test_completed_retry_and_database_authoritative_decision(self):
        first = self.record()
        second = self.record()
        self.assertEqual(str(first.change.threshold_percent), "17.25")
        self.assertFalse(first.change.exceeds_threshold)
        self.assertEqual(first.alert_status, "disabled")
        self.assertTrue(second.replayed)
        self.extract.assert_called_once()
        self.assertEqual(self.model.calls.count("rivalsense_record_verified_capture"), 1)

    def test_response_lost_after_payload_save_reuses_exact_payload(self):
        self.model.fail_save = True
        with self.assertRaises(HTTPException):
            self.record()
        receipt = self.model.receipts[str(self.key)]
        exact = receipt["payload"]
        self.record()
        self.assertEqual(receipt["payload"], exact)
        self.extract.assert_called_once()

    def test_response_lost_after_commit_returns_receipt(self):
        self.model.fail_record = True
        with self.assertRaises(HTTPException):
            self.record()
        result = self.record()
        self.assertTrue(result.replayed)
        self.extract.assert_called_once()

    def test_process_crash_before_save_is_not_rescraped(self):
        self.extract.side_effect = RuntimeError("simulated process crash")
        with self.assertRaises(RuntimeError):
            self.record()
        self.model.expired = True
        with self.assertRaises(HTTPException) as caught:
            self.record()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("unknown", caught.exception.detail)
        self.extract.assert_called_once()

    def test_concurrent_claims_have_one_extraction_owner(self):
        receipts = CaptureReceipts(self.repo)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: receipts.claim(LISTING, self.key), range(32)))
        self.assertEqual(sum(r["state"] == "extracting" for r in results), 1)
        self.assertEqual(sum(r["state"] == "busy" for r in results), 31)

    def test_key_cannot_be_reused_for_another_listing(self):
        self.record()
        with self.assertRaises(HTTPException) as caught:
            record_observation(self.repo, uuid4(), self.key)
        self.assertEqual(caught.exception.status_code, 409)
        self.extract.assert_called_once()

    def test_missing_secret_and_disabled_recording_fail_before_work(self):
        for values in ({"RIVALSENSE_RECORDING_ENABLED": "false"}, {"RIVALSENSE_RECORDING_SECRET": ""}):
            with patch.dict(os.environ, values):
                with self.assertRaises(HTTPException) as caught:
                    self.record()
                self.assertEqual(caught.exception.status_code, 503)
        self.extract.assert_not_called()
        self.repo.signed_rpc.assert_not_called()

    def test_failed_extraction_is_signed_without_inventing_price(self):
        bad = raw().model_copy(update={"status": "failure", "price": None, "error": "Provider timed out"})
        self.extract.return_value = (bad, 504)
        self.record()
        receipt = self.model.receipts[str(self.key)]
        payload = json.loads(receipt["payload"])
        self.assertEqual(payload["evidence"]["matching_status"], "unavailable")
        self.assertIsNone(payload["observation"]["price"])
        self.assertEqual(payload["observation"]["extraction_error"], "Provider timed out")

    def test_quota_denial_and_busy_do_not_extract(self):
        for state, code in (("limited", 429), ("busy", 409), ("indeterminate", 409), ("unknown", 503)):
            self.repo.signed_rpc.side_effect = None
            self.repo.signed_rpc.return_value = {"state": state, "retry_after": 60}
            with self.assertRaises(HTTPException) as caught:
                self.record()
            self.assertEqual(caught.exception.status_code, code)
        self.extract.assert_not_called()

    def test_malformed_database_result_does_not_leak_validation_details(self):
        self.model.execute = lambda *args: None
        self.repo.signed_rpc.side_effect = lambda *args: {"state": "completed", "result": {"secret": "never-return"}}
        with self.assertRaises(HTTPException) as caught:
            self.record()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("never-return", caught.exception.detail)
