"""Static deployment guardrails, NOT execution/permission/concurrency proof."""
from decimal import Decimal
from pathlib import Path
import re
import unittest

SQL = (Path(__file__).resolve().parents[1] / "migrations" / "PROPOSED_price_history.sql").read_text(encoding="utf-8")


class MigrationContractTests(unittest.TestCase):
    def test_public_wire_signatures_are_exact_and_definer_search_path_is_fixed(self):
        declarations = re.findall(r"CREATE FUNCTION public\.(\w+)\(([^)]*)\)\s*RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog", SQL)
        self.assertEqual(dict(declarations), {
            "rivalsense_rate_limit": "p_payload text,p_signature text",
            "rivalsense_capture_receipt": "p_payload text,p_signature text",
            "rivalsense_record_verified_capture": "p_payload text,p_signature text"})
        self.assertNotIn("CREATE FUNCTION public.rivalsense_record_observation", SQL)

    def test_alert_gate_is_separate_and_default_off(self):
        self.assertRegex(SQL, r"alerts_enabled boolean NOT NULL DEFAULT false")
        self.assertIn("IF cfg.alerts_enabled AND exceeds THEN", SQL)
        self.assertNotRegex(SQL, r"(?i)(SET\s+alerts_enabled\s*=\s*true|alerts_enabled\s+DEFAULT\s+true)")
        self.assertIn("IF r.state='completed' THEN RETURN r.result||", SQL)

    def test_money_boundary_reference_cases_for_documented_sql_formula(self):
        # Arithmetic specification examples, not a PostgreSQL numeric execution test.
        for old, new, threshold, expected in (
            ("100", "105", "5", False), ("100", "105.01", "5", True),
            ("100", "95", "5", False), ("100", "94.99", "5", True),
            ("0", "100", "5", False), ("100", "100", "0", False),
        ):
            old, new, threshold = map(Decimal, (old, new, threshold))
            self.assertEqual(old > 0 and abs(new-old)*100 > old*threshold, expected)
        self.assertIn("exceeds := abs(difference)*100 > previous.price*cfg.threshold_percent", SQL)

    def test_immutable_identity_and_history_retention_guardrails(self):
        self.assertIn("ROW(NEW.id,NEW.user_id,NEW.name,NEW.brand,NEW.sku,NEW.model_number,NEW.currency)", SQL)
        self.assertIn("ROW(NEW.id,NEW.user_id,NEW.product_id,NEW.product_url)", SQL)
        self.assertIn("ON DELETE NO ACTION", SQL)
        self.assertNotRegex(SQL, r"(?im)^\s*(DELETE FROM|TRUNCATE|DROP TABLE|ALTER TABLE auth\.)")
        self.assertIn("GRANT UPDATE(status) ON public.alerts TO authenticated", SQL)

    def test_receipts_fencing_replay_and_quota_shared_storage_guardrails(self):
        for required in ("PRIMARY KEY(user_id,request_key)", "UNIQUE(user_id,capture_event_id)",
                         "r.token IS DISTINCT FROM (p->>'token')::uuid",
                         "r.payload IS DISTINCT FROM p_payload", "SET state='completed',result=response",
                         "pg_advisory_xact_lock(192837465)", "used_min+p_units>cfg.per_user_minute",
                         "used_day+p_units>cfg.per_user_day", "used_global+p_units>cfg.global_minute",
                         "active>=cfg.per_user_concurrent"):
            self.assertIn(required, SQL)

    def test_transaction_and_role_constraints(self):
        self.assertIn("BEGIN;", SQL)
        self.assertIn("COMMIT;", SQL)
        self.assertIn("NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS", SQL)
        self.assertIn("GRANT SELECT ON rivalsense_private.recording_config TO rivalsense_recorder", SQL)
        self.assertNotIn("GRANT UPDATE ON rivalsense_private.recording_config", SQL)
        self.assertIn("FROM PUBLIC,anon,authenticated", SQL)
