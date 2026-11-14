"""Shared PostgreSQL quotas. No process-local fallback or client-controlled limits."""
import logging
from contextlib import contextmanager
from uuid import uuid4

from fastapi import HTTPException
from app.services.capture_receipts import command

logger = logging.getLogger(__name__)


@contextmanager
def extraction_budget(repository, units=1):
    reservation_id = str(uuid4())
    result = command(repository, "rivalsense_rate_limit", "quota",
                     operation="acquire", reservation_id=reservation_id, units=units)
    if not result.get("allowed"):
        raise HTTPException(429, "Extraction quota exceeded",
                            headers={"Retry-After": str(result.get("retry_after", 60))})
    try:
        yield
    finally:
        # Failure to release keeps the lease occupied until expiry; never hides
        # the extraction outcome and never repeats a provider request.
        try:
            command(repository, "rivalsense_rate_limit", "quota",
                    operation="release", reservation_id=reservation_id)
        except HTTPException:
            logger.warning("Extraction quota release failed; lease will expire")
