from support import PostgresCase


class TransactionTests(PostgresCase):
    def test_observation_and_completion_rollback_together(self):
        self.role(self.user)
        key,text,sig=self.ready()
        self.owner()
        self.execute("""CREATE FUNCTION pg_temp.rivalsense_fail_completion() RETURNS trigger
                        LANGUAGE plpgsql AS $$ BEGIN
                        IF NEW.state='completed' THEN
                          RAISE EXCEPTION 'synthetic completion failure' USING ERRCODE='P0001';
                        END IF; RETURN NEW; END $$""")
        self.execute("""CREATE TRIGGER rivalsense_test_completion_failure BEFORE UPDATE
                        ON rivalsense_private.capture_receipts FOR EACH ROW
                        EXECUTE FUNCTION pg_temp.rivalsense_fail_completion()""")
        self.role(self.user)
        self.denied(lambda: self.rpc("rivalsense_record_verified_capture",text,sig),"P0001")
        self.assertEqual(self.execute("SELECT count(*) FROM public.price_observations WHERE listing_id=%s",
                                      (self.listing,)).fetchone()[0],0)
        self.owner()
        self.assertEqual(self.execute("""SELECT state FROM rivalsense_private.capture_receipts
            WHERE user_id=%s AND request_key=%s""",(self.user,key)).fetchone()[0],"ready")
        self.execute("DROP TRIGGER rivalsense_test_completion_failure ON rivalsense_private.capture_receipts")
        self.role(self.user)
        self.assertFalse(self.rpc("rivalsense_record_verified_capture",text,sig)["replayed"])
        # The test transaction (including trigger/function DDL) is rolled back.

    def test_caller_rollback_leaves_no_observation_or_completed_receipt(self):
        self.role(self.user)
        key,text,sig=self.ready()
        self.execute("SAVEPOINT before_record")
        self.rpc("rivalsense_record_verified_capture",text,sig)
        self.execute("ROLLBACK TO SAVEPOINT before_record")
        self.assertEqual(self.execute("SELECT count(*) FROM public.price_observations WHERE listing_id=%s",
                                      (self.listing,)).fetchone()[0],0)
        self.assertFalse(self.rpc("rivalsense_record_verified_capture",text,sig)["replayed"])
