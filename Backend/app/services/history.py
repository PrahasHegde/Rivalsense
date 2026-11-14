"""Durable capture orchestration; PostgreSQL owns all history/change decisions."""
import os

from fastapi import HTTPException
from pydantic import ValidationError
from app.schemas.tracking import RecordResult
from app.services.capture_attestation import capture_payload, sign_capture
from app.services.capture_receipts import CaptureReceipts, require_receipt, signing_secret
from app.services.database import Repository
from app.services.extraction import extract_product


def record_observation(repository: Repository, listing_id, request_key) -> RecordResult:
    if os.getenv("RIVALSENSE_RECORDING_ENABLED", "false").lower() != "true":
        raise HTTPException(503, "Trusted recording is disabled pending migration verification")
    signing_secret()
    repository.get("competitor_listings", listing_id)
    receipts = CaptureReceipts(repository)
    receipt = require_receipt(receipts.claim(listing_id, request_key))
    if receipt["state"] == "completed":
        return validated_result({**receipt["result"], "replayed": True})
    if receipt["state"] == "extracting":
        raw, _ = extract_product(receipt["listing"]["product_url"])
        payload = capture_payload(repository.user_id, receipt["capture_event_id"],
                                  receipt["listing"], receipt["product"], raw)
        text, signature = sign_capture(payload, signing_secret())
        receipt = require_receipt(receipts.save(listing_id, request_key, receipt, text, signature))
    if receipt["state"] != "ready":
        raise HTTPException(503, "Capture payload was not durably saved")
    result = repository.signed_rpc("rivalsense_record_verified_capture",
                                   receipt["payload"], receipt["signature"])
    return validated_result(result)


def validated_result(result):
    try:
        return RecordResult.model_validate(result)
    except (ValidationError, TypeError):
        raise HTTPException(503, "Invalid recording service response; retry the same Idempotency-Key") from None
