"""Offline tests of integration safety gates. No driver or database required."""
import hashlib
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

DIRECTORY=Path(__file__).resolve().parent/"integration"
spec=importlib.util.spec_from_file_location("isolated_pg_support",DIRECTORY/"support.py")
support=importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def config():
    return dict(host="127.0.0.1",port=55432,database="rivalsense_test",
                user="test_owner",expected_user="test_owner",expected_address="127.0.0.1",
                expected_server_port=55432,expected_major=17,
                marker="11111111-1111-4111-8111-111111111111",tls=False)


class IntegrationGateTests(unittest.TestCase):
    def test_all_harness_sources_parse_without_driver_or_execution(self):
        paths=list(DIRECTORY.glob("*.py"))+[DIRECTORY.parents[1]/"scripts"/"test_postgres.py"]
        for path in paths:
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding="utf-8"),filename=path.name)

    def test_runner_refuses_missing_opt_in_before_driver_or_connection(self):
        spec=importlib.util.spec_from_file_location("isolated_pg_runner",DIRECTORY.parents[1]/"scripts"/"test_postgres.py")
        runner=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import patch
        with patch.object(runner.Runtime,"connect",side_effect=AssertionError("must not connect")) as connect:
            with redirect_stderr(StringIO()),self.assertRaises(SystemExit) as caught:
                runner.main([])
            self.assertEqual(caught.exception.code,2)
            connect.assert_not_called()

    def test_import_and_unactivated_runtime_do_not_connect(self):
        with self.assertRaises(unittest.SkipTest):
            support.runtime()

    def test_config_requires_explicit_exact_keys_and_safe_tls(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/"target.json"
            for changes in (None, {"tls":False,"host":"remote.example.com"}, {"password":"must-not-be-in-config"},
                            {"marker":"invalid"}, {"port":"5432"}):
                value=config()
                if changes:
                    value.update(changes)
                file.write_text(json.dumps(value),encoding="utf-8")
                if changes:
                    with self.assertRaises(support.SafetyError):
                        support.load_config(file)
                else:
                    self.assertEqual(support.load_config(file),value)

    def test_wrong_database_user_server_version_marker_or_fingerprint_is_rejected(self):
        c=config()
        identity=(c["database"],c["expected_user"],c["expected_address"],c["expected_server_port"],c["expected_major"])
        digest=hashlib.sha256((DIRECTORY.parents[1]/"migrations"/"PROPOSED_price_history.sql").read_bytes()).hexdigest()
        marker=(c["marker"],"rivalsense-isolated-integration",digest)
        support.check_identity(c,identity,marker)
        for index in range(len(identity)):
            changed=list(identity)
            changed[index]="wrong-target"
            with self.assertRaises(support.SafetyError):
                support.check_identity(c,changed,marker)
        for wrong in (None,(c["marker"],"production",digest),(c["marker"],marker[1],"0"*64)):
            with self.assertRaises(support.SafetyError):
                support.check_identity(c,identity,wrong)

    def test_failed_identity_verification_closes_connection_before_test_writes(self):
        driver=MagicMock()
        db=driver.connect.return_value
        db.cursor.return_value.fetchone.return_value=("wrong-database",)
        db.cursor.return_value.fetchall.return_value=[]
        with self.assertRaises(support.SafetyError):
            support.Runtime(config(),"test-only-unused-password",driver).connect()
        db.rollback.assert_called_once()
        db.close.assert_called_once()
        sql=[call.args[0] for call in db.cursor.return_value.execute.call_args_list]
        self.assertEqual(sql[0],"SET TRANSACTION READ ONLY")
        self.assertFalse(any(s.startswith(("INSERT","UPDATE","DELETE","CREATE","ALTER")) for s in sql))

    def test_connection_errors_hide_connection_details(self):
        driver=MagicMock()
        driver.connect.side_effect=RuntimeError("password=do-not-display")
        with self.assertRaises(support.SafetyError) as caught:
            support.Runtime(config(),"test-only-unused-password",driver).connect()
        self.assertNotIn("do-not-display",str(caught.exception))

    def test_enabled_alerts_or_non_test_secret_fail_before_test_writes(self):
        c=config()
        identity=(c["database"],c["expected_user"],c["expected_address"],c["expected_server_port"],c["expected_major"])
        digest=hashlib.sha256((DIRECTORY.parents[1]/"migrations"/"PROPOSED_price_history.sql").read_bytes()).hexdigest()
        for settings in ((True,True),(False,False),None):
            driver=MagicMock()
            db=driver.connect.return_value
            cur=db.cursor.return_value
            cur.fetchone.side_effect=[identity,settings]
            cur.fetchall.return_value=[(c["marker"],"rivalsense-isolated-integration",digest)]
            with self.assertRaises(support.SafetyError):
                support.Runtime(c,"test-only-unused-password",driver).connect()
            db.close.assert_called_once()
            db.commit.assert_not_called()

    def test_normal_discovery_does_not_collect_database_cases(self):
        # unittest recurses only through packages. Integration intentionally has
        # neither __init__.py nor test_*.py files.
        self.assertFalse((DIRECTORY/"__init__.py").exists())
        self.assertEqual(list(DIRECTORY.glob("test_*.py")),[])
        suite=unittest.defaultTestLoader.discover(str(DIRECTORY.parent),pattern="test_*.py")
        def flatten(suite):
            for item in suite:
                if isinstance(item,unittest.TestSuite):
                    yield from flatten(item)
                else:
                    yield item.id()
        self.assertFalse(any("pg_permissions." in name or "pg_concurrency." in name for name in flatten(suite)))
