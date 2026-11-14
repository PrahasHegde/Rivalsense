"""Verify Supabase access tokens and create isolated, user-scoped clients."""
import os
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from postgrest import SyncPostgrestClient

from app.core import config  # Loads .env without printing its contents.

bearer = HTTPBearer(auto_error=False)


@dataclass
class UserDatabase:
    user_id: str
    client: object = field(repr=False)


def unauthorized():
    return HTTPException(401, "Missing, invalid, or expired Supabase access token",
                         headers={"WWW-Authenticate": "Bearer"})


def get_user_database(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not url.startswith("https://") or not key.startswith("sb_publishable_"):
        raise HTTPException(503, "Supabase URL and publishable key are not configured")
    # One HTTP client per request, closed even on authentication/database failure.
    with httpx.Client(timeout=20, trust_env=False) as transport:
        try:
            response = transport.get(url.rstrip("/") + "/auth/v1/user", headers={
                "apikey": key, "Authorization": "Bearer " + credentials.credentials})
            if response.status_code in (400, 401, 403, 422):
                raise unauthorized() from None
            if response.status_code != 200:
                raise HTTPException(503, "Supabase authentication is unavailable")
            user_id = str(UUID(response.json()["id"]))
        except httpx.HTTPError:
            raise HTTPException(503, "Supabase authentication is unavailable") from None
        except (ValueError, KeyError, TypeError):
            raise unauthorized() from None
        # No mutable global token state; no refresh token or local JWT decoding.
        with SyncPostgrestClient(url.rstrip("/") + "/rest/v1", headers={
            "apikey": key, "Authorization": "Bearer " + credentials.credentials,
        }, http_client=transport, retry_enabled=False) as client:
            yield UserDatabase(user_id, client)
