# PostgreSQL validation harness — prepared, not executed

This work prepares files only. It does not authorize connecting to any database,
installing infrastructure, applying the proposal, seeding records, or enabling
alerts. Commit 62de835 and existing working changes are preserved.

Preparation validation (2026-11-14): 93 offline tests passed, including nine
integration-harness safety/syntax tests. The 31 prepared database cases were NOT
executed; one enabled-alert case is unconditionally skipped. No driver was installed,
no database connection was made, and no SQL fixture or migration was executed.

## Isolation and prerequisites

Use a disposable, exclusively assigned PostgreSQL target containing only synthetic
data. Do not use production, a production clone with customer records, or a
transaction-pooling endpoint. Use a direct/session connection: these tests require
SET LOCAL ROLE, session state, and independent concurrent connections.

For Windows ARM64, the separate integration requirements use pg8000, a pure Python
DB-API driver, avoiding a dependency on an architecture-matched libpq DLL.
Reference: https://pypi.org/project/pg8000/
The dependency is not installed by this work; validate its compatibility in a
separate integration virtual environment before an approved run. Existing backend
requirements and its environment are unchanged.

A dedicated hosted Supabase test project is the closest behavioral match without
assuming Docker/virtualization. Creating/selecting and connecting to one requires
separate approval. A standalone PostgreSQL cluster can exercise DB semantics with
the synthetic Auth fixture, but cannot certify Supabase Auth or PostgREST behavior.
Never run the standalone auth/schema fixture inside an existing Supabase project.

Use the same PostgreSQL major version/UTF-8 encoding as the eventual live target.
The owner connection must be able to seed synthetic auth.users/product/listing rows,
SET ROLE authenticated/anon, and create a transaction-local rollback-test trigger.
The standalone fixture additionally requires dedicated-cluster role/extension
creation authority. No external identity provider is called.

## Files and discovery

- scripts/test_postgres.py: opt-in runner, no automatic setup/migration/cleanup.
- tests/integration/support.py: identity gates, synthetic fixtures, signing helpers.
- pg_permissions.py: owner RLS, grants, protected alert fields, identity triggers.
- pg_signed_rpcs.py: exact signatures, Unicode HMAC parity, tampering, expiry, ownership.
- pg_receipts.py: busy/ready/completed replay, fencing, expiry, archival, numeric decisions.
- pg_concurrency.py: independent connections for claim/record/quota/baseline races.
- pg_transactions.py: savepoint rollback and failure injected after observation insert.
- pg_quotas.py: shared limits, multi-URL units, release/replay/expiry and rolling windows.
- fixtures/marker.sql: separately approved, manual dedicated-target marker setup.
- fixtures/base_schema.sql: manual empty-cluster simulation of inspected pre-migration schema.
- fixtures/test_settings.sql: manual fixed TEST-ONLY key setup; refuses enabled alerts.
- tests/test_integration_safety.py: offline gate tests, included in normal offline suite.

Integration modules are deliberately named pg_*.py and the directory has no
__init__.py. They are excluded from normal test_*.py discovery. Even explicit
discovery of pg_*.py skips database cases unless the runner activated a verified
runtime. Neither importing support nor requesting runner help makes a connection.
Do not add __init__.py or rename integration modules to test_*.py.

No harness module imports the application, dotenv, config.py, or a Supabase client.
It never loads the application's .env. It never invokes Context.dev, OAuth,
Supabase Auth, migrations, or shell database commands.

## Required manual setup — NOT authorized or executed yet

1. Separately approve the disposable target and its setup.
2. Confirm the target is empty/synthetic, its owner, server address/port, PostgreSQL
   major version, and dedicated marker UUID. Do not derive production credentials.
3. Manually install marker.sql with explicit psql variables test_marker and
   migration_sha256. It contains no password/key and will not reuse existing objects.
   Its digest must be the SHA-256 of the exact local PROPOSED_price_history.sql bytes
   that will be reviewed and manually applied; line-ending changes also change it.
4. For a standalone dedicated cluster ONLY, manually install base_schema.sql.
   Existing Supabase test projects instead need an explicitly reviewed synthetic
   recreation of the inspected application baseline; do not overwrite their Auth.
5. Separately authorize and manually apply the exact proposal in the isolated target.
   The harness never applies it and will refuse a missing/mismatched fingerprint.
6. In that isolated target ONLY, manually review test_settings.sql and configure signing_secret to the constant
   TEST_SECRET in support.py. It is public, fixed test material, never a production
   credential. Keep alerts_enabled=false. The harness reads only a boolean key
   comparison, never the secret value. It does not provision the key.
7. Check the proposed quotas, threshold, grants, and role authority; ensure no other
   jobs/users share the target. The tests use known quota/threshold settings inside
   transactions. Concurrency tests commit those test settings and synthetic fixtures.
8. Install requirements-integration.txt in a separate, approved integration venv.

For marker installation without psql, an administrator may review and translate
the psql variable directives into equivalent statements with explicitly supplied
test values. This translation is manual and outside harness execution.

## Explicit configuration

Store JSON outside Git or in an ignored *.local file, for example
Backend/postgres-target.local. No real config or password is supplied here.

Required keys, with illustrative NON-CONNECTING values:

~~~json
{
  "host": "127.0.0.1",
  "port": 55432,
  "database": "rivalsense_test",
  "user": "test_owner",
  "expected_user": "test_owner",
  "expected_address": "127.0.0.1",
  "expected_server_port": 55432,
  "expected_major": 17,
  "marker": "11111111-1111-4111-8111-111111111111",
  "tls": false
}
~~~

Use actual approved test values, not this example. Remote targets require tls=true
and certificate/hostname verification; non-TLS is allowed only for literal loopback.
expected_address is the value of inet_server_addr()::text on the approved server,
not necessarily the public DNS address. expected_server_port is inet_server_port(),
not necessarily a forwarding/pooler port. A changed address intentionally requires
a fresh explicit review. Config files cannot contain extra keys/passwords.

Supply only the dedicated test owner's password through RIVALSENSE_TEST_DB_PASSWORD
using a private process environment. Do not put it in command arguments, tracked
files, screenshots, or logs. No production secret is generated by the harness.

Before any test DML, each connection starts a READ ONLY transaction and verifies:
current_database(), current_user, server address/port, major version, exactly one
dedicated marker, matching migration digest, fixed TEST-ONLY key, and alerts off.
A mismatch closes the connection. Password/connection error details are withheld.
This is protection against mistakes, not against someone deliberately installing
the test marker/key into production. Never do that.

## Commands — documentation for a later, separately approved run

Help only (no connection or driver dependency):

~~~powershell
.\.venv\Scripts\python.exe scripts/test_postgres.py --help
~~~

After explicit test-connection/write approval, using the dedicated integration venv:

~~~powershell
python scripts/test_postgres.py --config postgres-target.local --run-writes
~~~

Concurrency cases additionally need --allow-committed-fixtures. Without it they
skip. That flag permits retained committed synthetic users, products, listings,
observations, receipts, and quota reservations; there is NO automatic deletion.
It does not authorize migration execution, alert enablement, or infrastructure.

Most tests use transactions and roll them back on completion. Quota settings are
set to the documented initial values in those transactions. Committed concurrency
fixtures persist, including test quota configuration. Do not run multiple harnesses
on one target. Repeated committed runs within the quota windows may exhaust shared
budgets; use a fresh approved target or wait for those windows, not a blind reset.
Any later purge or infrastructure teardown needs its own approval.

## Prepared coverage and limits

DB role tests simulate verified request JWT claim settings; they do NOT validate
JWT cryptography, token expiry at Supabase Auth, OAuth, or PostgREST forwarding.
Existing offline HTTP auth tests remain. Real Auth/PostgREST smoke tests require
a separately approved test project/HTTP stage.

Prepared DB cases cover client write denial, private schema isolation, two-owner
RLS, status-only alert updates, immutable identity, archival, exact RPC arguments,
Unicode HMAC, bad signatures, wrong user/action, expired commands, stale evidence,
receipt replay/busy/fencing/expiry, transaction rollback, shared quotas, multi-URL
charging, global/daily/minute/concurrency caps, and connection races.

Tests discard/retry already persisted results to model loss after save/commit;
they do not kill a real process or interrupt network traffic. Multi-process/forced
disconnect tests, migration apply/rollback, existing-row retention during actual
DDL, query plans, load, admin privilege variants/default ACLs, and real API gateway
behavior remain separate validation requirements.

The enabled-alert positive case is unconditionally skipped with an explicit reason.
There is no alerts_enabled=true statement or enablement option in this harness.
Alert insert/failure rollback while enabled remains untested until separate approval.

## Before any live migration

Complete read-only metadata exports and review effective grants, role SET/INHERIT,
owners, schema exposure, pgcrypto, version, and all existing policies/triggers.
Then obtain separate isolated setup/migration/run approvals, run this suite, resolve
failures, and review the exact final proposal and backup/locking/cutover plan.
The migration is not production-ready merely because offline tests pass.
Keep recording and alerts disabled until their independently approved rollout.
