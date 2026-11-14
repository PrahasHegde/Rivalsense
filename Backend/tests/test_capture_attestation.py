"""Offline contract tests. Concurrency model is NOT a PostgreSQL execution test."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from uuid import uuid4
import unittest

from app.services.capture_attestation import capture_payload, sign_capture, verify_capture
from app.services.history import detect_change
from test_tracking import product, listing, raw, observation, USER_A, USER_B
from decimal import Decimal

SECRET = "test-only-recording-secret-not-a-real-key"


class CaptureTests(unittest.TestCase):
    def payload(self):
        return capture_payload(USER_A, uuid4(), listing(), product(), raw())

    def test_signing_detects_tampering_and_cross_user_changes(self):
        payload = self.payload()
        text, signature = sign_capture(payload, SECRET)
        self.assertTrue(verify_capture(text, signature, SECRET))
        payload["user_id"] = USER_B
        changed, _ = sign_capture(payload, SECRET)
        self.assertFalse(verify_capture(changed, signature, SECRET))

    def test_mismatched_or_missing_evidence_cannot_be_confirmed_by_builder(self):
        for name in ("Different Mug", None):
            extracted = raw()
            extracted.product_name = name
            payload = capture_payload(USER_A, uuid4(), listing(), product(), extracted)
            self.assertEqual(payload["evidence"]["matching_status"], "needs_review")
            self.assertIsNone(payload["evidence"]["basis"])

    def test_confirmed_capture_has_reference_and_extracted_evidence(self):
        payload = self.payload()
        self.assertEqual(payload["evidence"]["matching_status"], "confirmed")
        self.assertEqual(payload["evidence"]["basis"], "name_and_sku")
        self.assertEqual(payload["evidence"]["reference"]["sku"], "M-100")
        self.assertNotIn("id", payload["observation"])

    def test_concurrent_event_replays_and_conflicts_model(self):
        # Mirrors the proposed lock + unique event key + immutable payload rule.
        # This does not establish PostgreSQL locking or RLS correctness.
        lock, events, alerts = Lock(), {}, set()
        payload = self.payload()

        def record(candidate, ignored_client_row_uuid):
            key = (candidate["user_id"], candidate["capture_event_id"])
            with lock:
                if key in events:
                    if events[key] != candidate:
                        raise ValueError("Conflicting replay")
                    return "replay"
                events[key] = deepcopy(candidate)
                alerts.add(key)
                return "created"

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: record(payload, uuid4()), range(32)))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(len(alerts), 1)
        changed = deepcopy(payload)
        changed["observation"]["price"] = "99.00"
        with self.assertRaises(ValueError):
            record(changed, uuid4())

    def test_threshold_boundaries_both_directions(self):
        old = observation("100.00")
        for price, exceeds in (("105.00", False), ("105.01", True), ("95.00", False), ("94.99", True)):
            current = observation(price, observed_at="2026-11-14T13:00:00+00:00")
            self.assertEqual(detect_change(old, current, Decimal(5)).exceeds_threshold, exceeds)
