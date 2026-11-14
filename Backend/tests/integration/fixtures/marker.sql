-- MANUAL PREPARATION ONLY, after separate isolated-database setup approval.
-- This file is NEVER run by the harness. Requires psql variables:
-- test_marker (a dedicated environment UUID), migration_sha256 (64 hex chars).
-- Do not put this marker in production. No DROP/DELETE or IF NOT EXISTS masking.
\if :{?test_marker}
\else
  \echo 'Missing test_marker; stopping'
  \quit 2
\endif
\if :{?migration_sha256}
\else
  \echo 'Missing migration_sha256; stopping'
  \quit 2
\endif
BEGIN;
CREATE SCHEMA rivalsense_test_control;
REVOKE ALL ON SCHEMA rivalsense_test_control FROM PUBLIC;
CREATE TABLE rivalsense_test_control.environment (
 marker uuid PRIMARY KEY,
 purpose text NOT NULL CHECK(purpose='rivalsense-isolated-integration'),
 migration_sha256 text NOT NULL CHECK(migration_sha256 ~ '^[0-9a-f]{64}$')
);
REVOKE ALL ON rivalsense_test_control.environment FROM PUBLIC;
INSERT INTO rivalsense_test_control.environment VALUES
 (:'test_marker'::uuid,'rivalsense-isolated-integration',:'migration_sha256');
COMMIT;
