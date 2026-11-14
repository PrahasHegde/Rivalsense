"""Real independent connections, opt-in committed fixtures, bounded synchronization."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from support import PostgresCase


class ConcurrentTests(PostgresCase):
    def parallel(self, operation, count=4):
        barrier=Barrier(count,timeout=15)
        def worker(index):
            db=self.runtime.connect()
            try:
                self.role(self.user,conn=db)
                barrier.wait()
                result=operation(db,index)
                db.commit()
                return result
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=count) as pool:
            futures=[pool.submit(worker,i) for i in range(count)]
            return [future.result(timeout=30) for future in futures]

    def test_same_key_claim_has_one_owner(self):
        self.committed_fixture()
        key=str(uuid4())
        values=self.parallel(lambda db,i:self.claim(key,conn=db)[2])
        self.assertEqual(sum(x["state"]=="extracting" for x in values),1)
        self.assertEqual(sum(x["state"]=="busy" for x in values),3)

    def test_same_ready_capture_records_once_even_after_response_is_discarded(self):
        self.role(self.user)
        _,text,sig=self.ready()
        self.committed_fixture()
        values=self.parallel(lambda db,i:self.rpc("rivalsense_record_verified_capture",text,sig,conn=db))
        self.assertEqual(len({x["observation"]["id"] for x in values}),1)
        self.assertEqual(sum(not x["replayed"] for x in values),1)
        self.role(self.user)
        self.assertTrue(self.rpc("rivalsense_record_verified_capture",text,sig)["replayed"])

    def test_quota_admission_is_shared_across_connections(self):
        self.committed_fixture()
        values=self.parallel(lambda db,i:self.command("rivalsense_rate_limit","quota",conn=db,
            operation="acquire",reservation_id=str(uuid4()),units=1))
        self.assertEqual(sum(x["allowed"] for x in values),2)

    def test_distinct_captures_serialize_baselines_for_one_listing(self):
        self.role(self.user)
        t=datetime.now(timezone.utc)-timedelta(seconds=10)
        self.record(price="100.00",when=t)
        captures=[self.ready(price=price,when=t+timedelta(seconds=offset))[1:]
                  for price,offset in (("110.00",2),("120.00",3))]
        self.committed_fixture()
        values=self.parallel(lambda db,i:self.rpc("rivalsense_record_verified_capture",*captures[i],conn=db),count=2)
        self.assertEqual(len({x["observation"]["id"] for x in values}),2)
        for result in values:
            self.assertEqual(result["alert_status"],"disabled")
            self.assertIsNone(result["alert"])
            self.assertIn(result["change"]["status"],("changed","out_of_order"))
            if result["change"]["status"]=="out_of_order":
                self.assertFalse(result["change"]["exceeds_threshold"])
        self.role(self.user)
        self.assertEqual(self.execute("SELECT count(*) FROM public.price_observations WHERE listing_id=%s",
                                      (self.listing,)).fetchone()[0],3)
