from uuid import uuid4
from support import PostgresCase


class QuotaTests(PostgresCase):
    def configure(self, field, value):
        if field not in ("per_user_minute","per_user_day","global_minute","per_user_concurrent"):
            raise ValueError("Unsupported quota setting")
        self.owner()
        self.execute("UPDATE rivalsense_private.recording_config SET "+field+"=%s WHERE singleton",(value,))
        self.role(self.user)

    def acquire(self, reservation=None, units=1, user=None):
        return self.command("rivalsense_rate_limit","quota",user=user,operation="acquire",
                            reservation_id=str(reservation or uuid4()),units=units)

    def release(self, reservation):
        return self.command("rivalsense_rate_limit","quota",operation="release",reservation_id=reservation)

    def test_minute_daily_global_and_concurrency_caps(self):
        for field in ("per_user_minute","per_user_day","global_minute","per_user_concurrent"):
            with self.subTest(field=field):
                self.execute("SAVEPOINT quota_case")
                self.configure(field,1)
                reservation=str(uuid4())
                self.assertTrue(self.acquire(reservation)["allowed"])
                if field!="per_user_concurrent":
                    self.release(reservation)
                self.assertFalse(self.acquire()["allowed"])
                self.execute("ROLLBACK TO SAVEPOINT quota_case")
                self.execute("RELEASE SAVEPOINT quota_case")

    def test_global_limit_is_shared_between_users(self):
        self.configure("global_minute",1)
        self.assertTrue(self.acquire()["allowed"])
        self.role(self.other)
        self.assertFalse(self.acquire(user=self.other)["allowed"])

    def test_comparison_units_and_failed_requests_remain_charged(self):
        self.configure("per_user_minute",3)
        reservation=str(uuid4())
        self.assertTrue(self.acquire(reservation,3)["allowed"])
        self.release(reservation)
        self.assertFalse(self.acquire()["allowed"])

    def test_reservation_replay_release_and_expiry(self):
        self.configure("per_user_concurrent",1)
        reservation=str(uuid4())
        self.assertTrue(self.acquire(reservation)["allowed"])
        self.assertFalse(self.acquire(reservation)["allowed"])
        self.release(reservation)
        self.release(reservation)
        another=str(uuid4())
        self.assertTrue(self.acquire(another)["allowed"])
        self.owner()
        self.execute("""UPDATE rivalsense_private.quota_reservations
            SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s""",(another,))
        self.role(self.user)
        self.assertTrue(self.acquire()["allowed"])

    def test_invalid_units_and_cross_owner_release(self):
        self.role(self.user)
        self.denied(lambda:self.acquire(units=0),"22023")
        reservation=str(uuid4())
        self.assertTrue(self.acquire(reservation)["allowed"])
        self.role(self.other)
        self.command("rivalsense_rate_limit","quota",user=self.other,operation="release",reservation_id=reservation)
        self.owner()
        self.assertFalse(self.execute("SELECT released FROM rivalsense_private.quota_reservations WHERE id=%s",
                                      (reservation,)).fetchone()[0])

    def test_capture_replays_do_not_reserve_new_quota(self):
        self.role(self.user)
        key,text,sig=self.ready()
        self.rpc("rivalsense_record_verified_capture",text,sig)
        self.command("rivalsense_capture_receipt","receipt",operation="claim",listing_id=self.listing,
                     request_key=key,token=str(uuid4()))
        self.owner()
        self.assertEqual(self.execute("SELECT count(*) FROM rivalsense_private.quota_reservations WHERE user_id=%s",
                                      (self.user,)).fetchone()[0],1)

    def test_rolling_windows_recover_after_reservations_age_out(self):
        self.configure("per_user_day",1)
        reservation=str(uuid4())
        self.assertTrue(self.acquire(reservation)["allowed"])
        self.release(reservation)
        self.assertFalse(self.acquire()["allowed"])
        self.owner()
        self.execute("""UPDATE rivalsense_private.quota_reservations
            SET created_at=clock_timestamp()-interval '2 days',
                expires_at=clock_timestamp()-interval '1 day' WHERE id=%s""",(reservation,))
        self.role(self.user)
        self.assertTrue(self.acquire()["allowed"])
