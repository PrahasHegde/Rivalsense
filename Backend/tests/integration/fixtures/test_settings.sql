-- MANUAL ISOLATED-TEST SETUP ONLY, after separate setup/migration approval.
-- Never executed by the runner. This PUBLIC TEST MATERIAL must NEVER be used
-- as a production signing key. No random/production secret is generated.
BEGIN;
DO $$ BEGIN
 IF (SELECT count(*) FROM rivalsense_test_control.environment
     WHERE purpose='rivalsense-isolated-integration')<>1 THEN
   RAISE EXCEPTION 'Dedicated test marker required';
 END IF;
 IF (SELECT alerts_enabled FROM rivalsense_private.recording_config WHERE singleton)
    IS DISTINCT FROM false THEN
   RAISE EXCEPTION 'Alerts must already be disabled; this fixture cannot toggle them';
 END IF;
END $$;
UPDATE rivalsense_private.recording_config
 SET signing_secret='rivalsense-isolated-test-only-secret-00000000' WHERE singleton;
COMMIT;
