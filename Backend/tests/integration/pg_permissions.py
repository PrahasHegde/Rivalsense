"""Actual database role/RLS/trigger checks; JWT claims are simulated, not Auth-issued."""
from support import PostgresCase, signed


class PermissionsTests(PostgresCase):
    def test_owner_and_cross_user_visibility(self):
        self.role(self.user)
        self.assertEqual(len(self.execute("SELECT id FROM public.products WHERE id=%s", (self.product,)).fetchall()), 1)
        self.role(self.other)
        self.assertEqual(self.execute("SELECT id FROM public.products WHERE id=%s", (self.product,)).fetchall(), [])
        self.assertEqual(self.execute("SELECT id FROM public.competitor_listings WHERE id=%s", (self.listing,)).fetchall(), [])
        self.assertEqual(self.execute("UPDATE public.products SET is_archived=true WHERE id=%s RETURNING id",
                                      (self.product,)).fetchall(), [])

    def test_clients_cannot_fabricate_history_or_alerts(self):
        self.role(self.user)
        self.denied(lambda: self.execute("""INSERT INTO public.price_observations
            (user_id,listing_id,price,currency,extraction_status,source_url)
            VALUES(%s,%s,1,'EUR','success','https://shop.example.com')""", (self.user,self.listing)))
        self.denied(lambda: self.execute("""INSERT INTO public.alerts(user_id,product_id,event_type,title)
            VALUES(%s,%s,'fabricated','Fake')""", (self.user,self.product)))
        for table in ("price_observations","alerts","products","competitor_listings"):
            self.denied(lambda table=table: self.execute("DELETE FROM public."+table+" WHERE false"))
        self.denied(lambda: self.execute("SELECT * FROM rivalsense_private.recording_config"))

    def test_alert_status_only_and_cross_user_protection(self):
        alert = self.execute("""INSERT INTO public.alerts(user_id,product_id,event_type,title)
            VALUES(%s,%s,'fixture','Synthetic fixture') RETURNING id""", (self.user,self.product)).fetchone()[0]
        self.role(self.user)
        self.assertEqual(self.execute("UPDATE public.alerts SET status='read' WHERE id=%s RETURNING status",
                                      (alert,)).fetchone()[0], "read")
        for column, value in (("title","Changed"),("new_price","1.00"),("user_id",self.other)):
            self.denied(lambda column=column,value=value: self.execute(
                "UPDATE public.alerts SET "+column+"=%s WHERE id=%s", (value,alert)))
        self.role(self.other)
        self.assertEqual(self.execute("UPDATE public.alerts SET status='resolved' WHERE id=%s RETURNING id",
                                      (alert,)).fetchall(), [])

    def test_archive_and_deactivate_preserve_history(self):
        self.role(self.user)
        saved = self.record()
        self.execute("UPDATE public.products SET is_archived=true WHERE id=%s", (self.product,))
        self.execute("UPDATE public.competitor_listings SET is_active=false WHERE id=%s", (self.listing,))
        self.assertEqual(self.execute("SELECT id FROM public.price_observations WHERE id=%s",
                                      (saved["observation"]["id"],)).fetchone()[0].__str__(), saved["observation"]["id"])
        self.denied(lambda: self.claim(), "22023")

    def test_identity_acl_and_trigger_are_both_enforced(self):
        self.role(self.user)
        self.denied(lambda: self.execute("UPDATE public.products SET name='Other' WHERE id=%s", (self.product,)))
        self.denied(lambda: self.execute("UPDATE public.competitor_listings SET product_url='https://other.example.com' WHERE id=%s",
                                         (self.listing,)))
        self.owner()
        self.denied(lambda: self.execute("UPDATE public.products SET name='Other' WHERE id=%s", (self.product,)), "22023")
        self.denied(lambda: self.execute("UPDATE public.competitor_listings SET product_url='https://other.example.com' WHERE id=%s",
                                         (self.listing,)), "22023")

    def test_authenticated_without_subject_and_anon_cannot_record(self):
        text, signature = signed(self.user,"quota",operation="acquire",reservation_id=self.product,units=1)
        self.role()
        self.denied(lambda: self.rpc("rivalsense_rate_limit",text,signature))
        self.role(role="anon")
        self.denied(lambda: self.rpc("rivalsense_rate_limit",text,signature))

    def test_recorder_is_non_owner_and_unreachable_from_clients(self):
        row = self.execute("""SELECT rolsuper,rolbypassrls,rolcanlogin FROM pg_roles
                              WHERE rolname='rivalsense_recorder'""").fetchone()
        self.assertEqual(tuple(row),(False,False,False))
        for role in ("anon","authenticated","authenticator"):
            self.assertFalse(self.execute("SELECT pg_has_role(%s,'rivalsense_recorder','MEMBER')",(role,)).fetchone()[0])
        self.assertEqual(self.execute("""SELECT count(*) FROM pg_class
            WHERE oid IN ('public.products'::regclass,'public.competitor_listings'::regclass,
                          'public.price_observations'::regclass,'public.alerts'::regclass)
            AND (NOT relrowsecurity OR relowner=(SELECT oid FROM pg_roles WHERE rolname='rivalsense_recorder'))""").fetchone()[0],0)
