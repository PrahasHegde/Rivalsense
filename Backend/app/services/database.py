"""All queries keep explicit owner filters in addition to Supabase RLS."""
from fastapi import HTTPException
from postgrest.exceptions import APIError
import httpx

from app.core.auth import UserDatabase


def execute(query):
    try:
        return query.execute().data
    except APIError as exc:
        if exc.code == "23505":
            raise HTTPException(409, "A record with this identifier already exists") from None
        if exc.code in ("42501", "23503"):
            raise HTTPException(403, "Database operation is not permitted") from None
        raise HTTPException(503, "Database operation failed; verify schema and configuration") from None
    except httpx.HTTPError:
        raise HTTPException(503, "Database is unavailable") from None


class Repository:
    def __init__(self, session: UserDatabase):
        self.client = session.client
        self.user_id = session.user_id

    def select(self, table):
        return self.client.from_(table).select("*").eq("user_id", self.user_id)

    def get(self, table, identifier):
        rows = execute(self.select(table).eq("id", str(identifier)).limit(1))
        if not rows:
            raise HTTPException(404, "Record not found")
        return rows[0]

    def list(self, table, limit, offset, **filters):
        query = self.select(table)
        for key, value in filters.items():
            query = query.eq(key, str(value))
        time_field = "observed_at" if table == "price_observations" else "created_at"
        return execute(query.order(time_field, desc=True).order("id", desc=True).range(offset, offset + limit - 1))

    def insert(self, table, values):
        rows = execute(self.client.from_(table).insert({**values, "user_id": self.user_id}))
        if not rows:
            raise HTTPException(503, "Database returned no inserted record")
        return rows[0]

    def signed_rpc(self, name, payload, signature):
        allowed = {"rivalsense_record_verified_capture", "rivalsense_capture_receipt", "rivalsense_rate_limit"}
        if name not in allowed:
            raise ValueError("Unsupported signed RPC")
        try:
            result = self.client.rpc(name, {"p_payload": payload, "p_signature": signature}).execute().data
        except APIError as exc:
            if exc.code in ("23505", "22023"):
                raise HTTPException(409, "Capture conflicts with the stored identity or receipt") from None
            if exc.code == "42501":
                raise HTTPException(403, "Signed operation is not permitted") from None
            raise HTTPException(503, "Recording service unavailable; retry with the same Idempotency-Key") from None
        except httpx.HTTPError:
            raise HTTPException(503, "Recording service unavailable; retry with the same Idempotency-Key") from None
        if not isinstance(result, dict):
            raise HTTPException(503, "Invalid recording service response")
        return result

    def update(self, table, identifier, values):
        self.get(table, identifier)
        rows = execute(self.client.from_(table).update(values).eq("user_id", self.user_id).eq("id", str(identifier)))
        if not rows:
            raise HTTPException(404, "Record not found")
        return rows[0]
