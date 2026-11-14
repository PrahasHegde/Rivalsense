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

    def existing_observation(self, identifier, listing_id):
        rows = execute(self.select("price_observations").eq("id", str(identifier)).limit(1))
        if rows and rows[0]["listing_id"] != str(listing_id):
            raise HTTPException(409, "Idempotency key was used for another listing")
        return rows[0] if rows else None

    def previous_valid(self, listing_id, currency):
        query = self.select("price_observations").eq("listing_id", str(listing_id)).eq(
            "currency", currency).eq("matching_status", "confirmed").in_(
            "extraction_status", ["success", "partial"]).not_.is_("price", "null")
        rows = execute(query.order("observed_at", desc=True).order("id", desc=True).limit(1))
        return rows[0] if rows else None

    def record_atomic(self, listing_id, observation, previous_id, alert):
        # Only available after the separately approved SQL migration.
        try:
            return self.client.rpc("rivalsense_record_observation", {
                "p_listing_id": str(listing_id), "p_observation": observation,
                "p_previous_id": previous_id, "p_alert": alert,
            }).execute().data
        except APIError as exc:
            if exc.code == "40001":
                return None  # Concurrent observation changed the baseline; recompute.
            if exc.code == "23505":
                raise HTTPException(409, "Observation identifier conflict") from None
            raise HTTPException(503, "Atomic recording failed; verify the approved migration") from None
        except httpx.HTTPError:
            raise HTTPException(503, "Database is unavailable") from None
