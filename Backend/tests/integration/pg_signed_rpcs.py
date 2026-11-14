from datetime import datetime, timezone, timedelta
import hmac
import hashlib
import json
from uuid import uuid4
from support import PostgresCase, signed, TEST_SECRET


class SignedRPCTests(PostgresCase):
    def test_unicode_hmac_matches_python_and_exact_wire_signatures(self):
        text = '{"name":"Mökki ☕"}'
        expected = hmac.new(TEST_SECRET.encode(),text.encode(),hashlib.sha256).hexdigest()
        self.assertEqual(self.execute("""SELECT encode(extensions.hmac(convert_to(%s,'UTF8'),
                          convert_to(%s,'UTF8'),'sha256'),'hex')""",(text,TEST_SECRET)).fetchone()[0],expected)
        for name in ("rivalsense_rate_limit","rivalsense_capture_receipt","rivalsense_record_verified_capture"):
            self.assertEqual(self.execute("""SELECT pg_get_function_identity_arguments(oid) FROM pg_proc
                WHERE oid=to_regprocedure(%s)""",("public."+name+"(text,text)",)).fetchone()[0],"p_payload text, p_signature text")

    def test_missing_wrong_and_tampered_signatures_are_denied(self):
        self.role(self.user)
        text,sig = signed(self.user,"quota",operation="acquire",reservation_id=str(uuid4()),units=1)
        for value in (None, "0"*64, "bad"):
            self.denied(lambda value=value: self.rpc("rivalsense_rate_limit",text,value))
        self.denied(lambda: self.rpc("rivalsense_rate_limit",text+" ",sig))

    def test_wrong_owner_action_and_expired_command(self):
        self.role(self.other)
        self.denied(lambda: self.rpc("rivalsense_rate_limit",*signed(self.user,"quota",operation="release",reservation_id=str(uuid4()))))
        self.role(self.user)
        self.denied(lambda: self.rpc("rivalsense_rate_limit",*signed(self.user,"receipt",operation="claim")))
        old = (datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
        self.denied(lambda: self.rpc("rivalsense_rate_limit",*signed(self.user,"quota",issued_at=old,operation="release",reservation_id=str(uuid4()))))

    def test_missing_receipt_and_stale_reference_are_rejected(self):
        self.role(self.user)
        key,token,r = self.claim()
        text,sig = self.payload(r)
        self.denied(lambda: self.rpc("rivalsense_record_verified_capture",text,sig))
        payload=json.loads(text)
        payload["evidence"]["reference"]["name"]="Different"
        # Save the signed but stale payload: final DB evidence validation must reject it.
        changed=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        signature=hmac.new(TEST_SECRET.encode(),changed.encode(),hashlib.sha256).hexdigest()
        self.command("rivalsense_capture_receipt","receipt",operation="save",request_key=key,token=token,
                     listing_id=self.listing,payload=changed,signature=signature)
        self.denied(lambda: self.rpc("rivalsense_record_verified_capture",changed,signature),"22023")
