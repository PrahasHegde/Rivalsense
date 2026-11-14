"""Signed commands for durable, private PostgreSQL capture receipts."""
import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from app.services.capture_attestation import sign_capture


def signing_secret():
    secret = os.getenv("RIVALSENSE_RECORDING_SECRET", "")
    if len(secret.encode("utf-8")) < 32:
        raise HTTPException(503, "Trusted recording is not configured")
    return secret


def command(repository, rpc, action, **fields):
    payload = {"version": 1, "action": action, "user_id": repository.user_id,
               "issued_at": datetime.now(timezone.utc).isoformat(), **fields}
    text, signature = sign_capture(payload, signing_secret())
    return repository.signed_rpc(rpc, text, signature)


class CaptureReceipts:
    def __init__(self, repository):
        self.repository = repository

    def claim(self, listing_id, request_key):
        return command(self.repository, "rivalsense_capture_receipt", "receipt",
                       operation="claim", listing_id=str(listing_id),
                       request_key=str(request_key), token=str(uuid4()))

    def save(self, listing_id, request_key, receipt, payload, signature):
        return command(self.repository, "rivalsense_capture_receipt", "receipt",
                       operation="save", listing_id=str(listing_id), request_key=str(request_key),
                       token=receipt["token"], payload=payload, signature=signature)


def require_receipt(result):
    state = result.get("state")
    if state == "limited":
        raise HTTPException(429, "Extraction quota exceeded", headers={"Retry-After": str(result.get("retry_after", 60))})
    if state == "busy":
        raise HTTPException(409, "Capture is already processing; retry the same Idempotency-Key",
                            headers={"Retry-After": "5"})
    if state == "indeterminate":
        raise HTTPException(409, "Capture outcome is unknown; a new explicit capture needs a new Idempotency-Key")
    if state not in ("extracting", "ready", "completed"):
        raise HTTPException(503, "Invalid capture receipt response")
    return result
