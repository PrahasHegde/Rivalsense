"""Explicitly activated PostgreSQL test support. No app imports, dotenv, or import-time I/O."""
import hashlib
import hmac
import json
from pathlib import Path
import ssl
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
import unittest

TEST_SECRET = "rivalsense-isolated-test-only-secret-00000000"
RPCS = {"rivalsense_rate_limit", "rivalsense_capture_receipt", "rivalsense_record_verified_capture"}
_runtime = None


class SafetyError(RuntimeError):
    pass


def load_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
        required = {"host", "port", "database", "user", "expected_user", "expected_address",
                    "expected_server_port", "expected_major", "marker", "tls"}
        if set(config) != required or not all(config[k] for k in required - {"tls"}):
            raise ValueError()
        UUID(config["marker"])
        for key in ("port", "expected_server_port", "expected_major"):
            if type(config[key]) is not int or config[key] < 1:
                raise ValueError()
        if type(config["tls"]) is not bool:
            raise ValueError()
        if not config["tls"] and config["host"] not in ("127.0.0.1", "::1"):
            raise ValueError()
        return config
    except (OSError, ValueError, TypeError):
        raise SafetyError("Invalid explicit test configuration; see postgres-validation.md") from None


def check_server(config, actual):
    # actual includes server address/port to reject accidentally redirected connections.
    expected = (config["database"], config["expected_user"], config["expected_address"],
                config["expected_server_port"], config["expected_major"])
    if tuple(actual) != expected:
        raise SafetyError("Connected database identity does not match the approved test target")


def check_identity(config, actual, marker):
    check_server(config, actual)
    migration = Path(__file__).resolve().parents[2] / "migrations" / "PROPOSED_price_history.sql"
    digest = hashlib.sha256(migration.read_bytes()).hexdigest()
    if marker != (config["marker"], "rivalsense-isolated-integration", digest):
        raise SafetyError("Missing/mismatched dedicated test marker or migration fingerprint")


class Runtime:
    def __init__(self, config, password, driver, committed=False):
        self.config, self.password, self.driver = config, password, driver
        self.committed = committed

    def connect(self):
        c = self.config
        try:
            conn = self.driver.connect(host=c["host"], port=c["port"], database=c["database"],
                                       user=c["user"], password=self.password, timeout=10,
                                       ssl_context=ssl.create_default_context() if c["tls"] else False)
        except Exception:
            raise SafetyError("Test connection failed; connection details withheld") from None
        try:
            cur = conn.cursor()
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("""SELECT current_database(),current_user,inet_server_addr()::text,
                           inet_server_port(),current_setting('server_version_num')::integer/10000""")
            identity = cur.fetchone()
            check_server(c, identity)
            cur.execute("""SELECT marker::text,purpose,migration_sha256
                           FROM rivalsense_test_control.environment""")
            markers = cur.fetchall()
            check_identity(c, identity, tuple(markers[0]) if len(markers) == 1 else None)
            # Fixed test secret only; never retrieve any configured secret.
            cur.execute("""SELECT signing_secret=%s,alerts_enabled
                           FROM rivalsense_private.recording_config WHERE singleton""", (TEST_SECRET,))
            settings = cur.fetchone()
            if settings is None or tuple(settings) != (True, False):
                raise SafetyError("Target must use the fixed TEST-ONLY key and have alerts disabled")
            conn.rollback()
            cur.execute("SET statement_timeout='8s'")
            cur.execute("SET lock_timeout='3s'")
            conn.commit()
            return conn
        except Exception:
            conn.rollback()
            conn.close()
            raise SafetyError("Test target verification failed; no test writes authorized") from None


def activate(runtime):
    global _runtime
    _runtime = runtime


def runtime():
    if _runtime is None:
        raise unittest.SkipTest("Integration suite requires scripts/test_postgres.py and explicit verified target")
    return _runtime


def signed(user, action, **fields):
    payload = {"version": 1, "action": action, "user_id": str(user),
               "issued_at": datetime.now(timezone.utc).isoformat(), **fields}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return text, hmac.new(TEST_SECRET.encode(), text.encode(), hashlib.sha256).hexdigest()


def sqlstate(error):
    for arg in error.args:
        if isinstance(arg, dict):
            return arg.get("C")
    return None


class PostgresCase(unittest.TestCase):
    def setUp(self):
        self.runtime = runtime()
        self.db = self.runtime.connect()
        self.addCleanup(self.finish)
        self.execute("""UPDATE rivalsense_private.recording_config SET threshold_percent=5,
                        per_user_minute=10,per_user_day=200,global_minute=60,
                        per_user_concurrent=2,lease_seconds=900 WHERE singleton""")
        self.user, self.other, self.product, self.listing = map(str, (uuid4(), uuid4(), uuid4(), uuid4()))
        self.seed(self.db)

    def finish(self):
        self.db.rollback()
        self.db.close()

    def execute(self, sql, params=(), conn=None):
        cur = (conn or self.db).cursor()
        cur.execute(sql, params)
        return cur

    def seed(self, conn):
        # Test owner connection only. Never invoke Auth APIs or create real accounts.
        self.execute("INSERT INTO auth.users(id) VALUES(%s),(%s)", (self.user, self.other), conn)
        self.execute("""INSERT INTO public.products(id,user_id,name,brand,sku,selling_price,currency)
                        VALUES(%s,%s,'Mökki Mug','Acme','M-1',120,'EUR')""",
                     (self.product, self.user), conn)
        self.execute("""INSERT INTO public.competitor_listings(id,user_id,product_id,competitor_name,product_url)
                        VALUES(%s,%s,%s,'Synthetic shop','https://shop.example.com/mug')""",
                     (self.listing, self.user, self.product), conn)

    def role(self, user=None, role="authenticated", conn=None):
        if role not in ("authenticated", "anon"):
            raise ValueError("Unsupported test role")
        db = conn or self.db
        self.execute("RESET ROLE", conn=db)
        self.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (user or "",), db)
        self.execute("SELECT set_config('request.jwt.claims',%s,true)",
                     (json.dumps({"sub": user, "role": role}) if user else "{}",), db)
        self.execute("SET LOCAL ROLE " + role, conn=db)

    def owner(self, conn=None):
        self.execute("RESET ROLE", conn=conn)
        self.execute("SELECT set_config('request.jwt.claim.sub','',true)", conn=conn)
        self.execute("SELECT set_config('request.jwt.claims','{}',true)", conn=conn)

    def rpc(self, name, text, signature, conn=None):
        if name not in RPCS:
            raise ValueError("RPC not allowlisted")
        return self.execute("SELECT public." + name + "(%s,%s)",
                            (text, signature), conn).fetchone()[0]

    def command(self, name, action, conn=None, user=None, **fields):
        return self.rpc(name, *signed(user or self.user, action, **fields), conn=conn)

    def claim(self, key=None, token=None, conn=None):
        key, token = str(key or uuid4()), str(token or uuid4())
        value = self.command("rivalsense_capture_receipt", "receipt", conn=conn, operation="claim",
                             listing_id=self.listing, request_key=key, token=token)
        return key, token, value

    def payload(self, receipt, price="100.00", when=None, currency="EUR", match="confirmed"):
        payload = {
            "version": 1, "action": "record", "user_id": self.user,
            "capture_event_id": receipt["capture_event_id"], "listing_id": self.listing,
            "product_url": "https://shop.example.com/mug",
            "observation": {"price": price, "currency": currency, "availability": "in_stock",
                "source_url": "https://shop.example.com/mug", "extraction_status": "success",
                "observed_at": (when or datetime.now(timezone.utc)).isoformat()},
            "evidence": {"validator": "rivalsense-identity-v1", "reference": {
                "name": "Mökki Mug", "brand": "Acme", "sku": "M-1", "model_number": None},
                "matching_status": match, "basis": "name_and_sku",
                "extracted": {"product_name": "Mökki Mug", "sku": "M-1", "brand": "Acme"}}
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return text, hmac.new(TEST_SECRET.encode(), text.encode(), hashlib.sha256).hexdigest()

    def ready(self, price="100.00", when=None, currency="EUR", match="confirmed"):
        key, token, receipt = self.claim()
        self.assertEqual(receipt["state"], "extracting")
        text, signature = self.payload(receipt, price, when, currency, match)
        saved = self.command("rivalsense_capture_receipt", "receipt", operation="save", listing_id=self.listing,
                             request_key=key, token=token, payload=text, signature=signature)
        self.assertEqual(saved["state"], "ready")
        return key, text, signature

    def record(self, **fields):
        _, text, signature = self.ready(**fields)
        return self.rpc("rivalsense_record_verified_capture", text, signature)

    def denied(self, operation, expected="42501"):
        # A failed statement must not abort the enclosing fixture transaction.
        self.execute("SAVEPOINT denied_operation")
        try:
            operation()
        except Exception as error:
            self.execute("ROLLBACK TO SAVEPOINT denied_operation")
            self.assertEqual(sqlstate(error), expected, "Unexpected SQLSTATE (error details withheld)")
        else:
            self.fail("Operation unexpectedly succeeded")
        finally:
            self.execute("RELEASE SAVEPOINT denied_operation")

    def committed_fixture(self):
        if not self.runtime.committed:
            self.skipTest("Requires additional --allow-committed-fixtures flag")
        # Deliberately retained; never automatically delete committed synthetic rows.
        self.db.commit()
