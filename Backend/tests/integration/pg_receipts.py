from datetime import datetime, timezone, timedelta
from uuid import uuid4
import unittest
from support import PostgresCase


class ReceiptTests(PostgresCase):
    def test_ready_and_completed_retries_return_same_capture(self):
        self.role(self.user)
        key,text,sig=self.ready()
        ready=self.command("rivalsense_capture_receipt","receipt",operation="claim",
                           listing_id=self.listing,request_key=key,token=str(uuid4()))
        self.assertEqual((ready["payload"],ready["signature"]),(text,sig))
        first=self.rpc("rivalsense_record_verified_capture",text,sig)
        second=self.rpc("rivalsense_record_verified_capture",text,sig)
        self.assertTrue(second["replayed"])
        self.assertEqual(first["observation"]["id"],second["observation"]["id"])
        self.assertEqual(first["change"],second["change"])
        completed=self.command("rivalsense_capture_receipt","receipt",operation="claim",
                               listing_id=self.listing,request_key=key,token=str(uuid4()))
        self.assertEqual(completed["state"],"completed")
        self.assertEqual(self.execute("SELECT count(*) FROM public.price_observations WHERE listing_id=%s",
                                      (self.listing,)).fetchone()[0],1)

    def test_busy_conflicting_key_and_stale_fence(self):
        self.role(self.user)
        key,token,r=self.claim()
        _,_,busy=self.claim(key)
        self.assertEqual(busy["state"],"busy")
        text,sig=self.payload(r)
        self.denied(lambda: self.command("rivalsense_capture_receipt","receipt",operation="save",
            listing_id=self.listing,request_key=key,token=str(uuid4()),payload=text,signature=sig))
        self.denied(lambda: self.command("rivalsense_capture_receipt","receipt",operation="claim",
            listing_id=str(uuid4()),request_key=key,token=token),"23505")

    def test_expiry_is_indeterminate_and_late_save_is_not_accepted(self):
        self.role(self.user)
        key,token,r=self.claim()
        text,sig=self.payload(r)
        self.owner()
        self.execute("""UPDATE rivalsense_private.capture_receipts SET expires_at=clock_timestamp()-interval '1 second'
                        WHERE user_id=%s AND request_key=%s""",(self.user,key))
        self.role(self.user)
        result=self.command("rivalsense_capture_receipt","receipt",operation="save",listing_id=self.listing,
                            request_key=key,token=token,payload=text,signature=sig)
        self.assertEqual(result["state"],"indeterminate")
        self.assertEqual(self.execute("SELECT count(*) FROM public.price_observations WHERE listing_id=%s",
                                      (self.listing,)).fetchone()[0],0)

    def test_archival_between_capture_and_record_is_rejected(self):
        self.role(self.user)
        _,text,sig=self.ready()
        self.execute("UPDATE public.products SET is_archived=true WHERE id=%s",(self.product,))
        self.denied(lambda: self.rpc("rivalsense_record_verified_capture",text,sig),"22023")

    def test_database_threshold_and_disabled_alerts_both_directions(self):
        for price,expected in (("105.00",False),("105.01",True),("95.00",False),("94.99",True)):
            with self.subTest(price=price):
                # Savepoint gives each case the same empty baseline and quota state.
                self.execute("SAVEPOINT boundary_case")
                self.role(self.user)
                t=datetime.now(timezone.utc)-timedelta(seconds=10)
                self.record(price="100.00",when=t)
                result=self.record(price=price,when=t+timedelta(seconds=1))
                self.assertEqual(result["change"]["exceeds_threshold"],expected)
                self.assertEqual(result["change"]["threshold_percent"],"5")
                self.assertEqual(result["alert_status"],"disabled")
                self.assertIsNone(result["alert"])
                self.execute("ROLLBACK TO SAVEPOINT boundary_case")
                self.execute("RELEASE SAVEPOINT boundary_case")
        self.assertEqual(self.execute("SELECT count(*) FROM public.alerts WHERE user_id=%s",(self.user,)).fetchone()[0],0)

    def test_zero_out_of_order_and_currency_baselines(self):
        self.role(self.user)
        t=datetime.now(timezone.utc)-timedelta(seconds=10)
        self.assertEqual(self.record(price="0.00",when=t)["change"]["status"],"no_baseline")
        self.assertEqual(self.record(price="100.00",when=t+timedelta(seconds=2))["change"]["status"],"zero_baseline")
        self.assertEqual(self.record(price="80.00",when=t+timedelta(seconds=1))["change"]["status"],"out_of_order")
        self.assertEqual(self.record(currency="USD")["change"]["status"],"no_baseline")
        self.assertEqual(self.record(match="needs_review")["change"]["status"],"not_comparable")

    @unittest.skip("Enabling alerts requires separate explicit approval; no enablement code is included")
    def test_enabled_alert_creation_and_duplicate_suppression(self):
        pass
