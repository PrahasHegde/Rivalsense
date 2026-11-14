"""Opt-in integration runner. No dotenv, automatic migration, setup, or cleanup."""
import argparse
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "tests" / "integration"
sys.path.insert(0, str(DIRECTORY))
from support import Runtime, SafetyError, activate, load_config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Explicit private JSON target config; never .env")
    parser.add_argument("--run-writes", action="store_true", help="Separately approved test-record writes")
    parser.add_argument("--allow-committed-fixtures", action="store_true",
                        help="Also permit retained committed synthetic fixtures for concurrency tests")
    args = parser.parse_args(argv)
    if not args.run_writes or args.config is None:
        parser.error("--config and --run-writes are required; no database connection attempted")
    password = os.environ.get("RIVALSENSE_TEST_DB_PASSWORD")
    if not password:
        parser.error("Explicit RIVALSENSE_TEST_DB_PASSWORD is required; no .env is read")
    try:
        config = load_config(args.config)
        # Lazy import: --help, refusal, and offline checks require no driver.
        import pg8000.dbapi
        target = Runtime(config, password, pg8000.dbapi, args.allow_committed_fixtures)
        conn = target.connect()
        conn.close()
    except ImportError:
        print("Install requirements-integration.txt in a separate test environment.", file=sys.stderr)
        return 2
    except SafetyError as error:
        print(str(error), file=sys.stderr)
        return 2
    activate(target)
    suite = unittest.defaultTestLoader.discover(str(DIRECTORY), pattern="pg_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
