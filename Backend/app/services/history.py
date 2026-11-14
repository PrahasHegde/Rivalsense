"""Append real observations; confirmed alerts require the approved atomic RPC."""
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from uuid import UUID

from fastapi import HTTPException
from app.schemas.comparison import CompareRequest
from app.schemas.tracking import ChangeResult, RecordResult
from app.services.comparison import identity
from app.services.database import Repository
from app.services.extraction import extract_product


def settings():
    try:
        threshold = Decimal(os.getenv("PRICE_CHANGE_THRESHOLD_PERCENT", "5"))
        if not threshold.is_finite() or not 0 <= threshold <= 10000 or len(threshold.as_tuple().digits) > 10:
            raise ValueError()
    except (InvalidOperation, ValueError):
        raise HTTPException(503, "Invalid price-change threshold configuration") from None
    return threshold, os.getenv("SUPABASE_PRICE_HISTORY_RPC_ENABLED", "false").lower() == "true"


def detect_change(previous, current, threshold: Decimal) -> ChangeResult:
    result = ChangeResult(status="no_baseline", threshold_percent=threshold)
    if current.get("matching_status") != "confirmed" or current["extraction_status"] == "failure" or current["price"] is None or not current["currency"]:
        return result.model_copy(update={"status": "not_comparable"})
    if previous is None:
        return result
    if previous.get("matching_status") != "confirmed" or previous["extraction_status"] == "failure" or previous["price"] is None or previous["currency"] != current["currency"]:
        return result.model_copy(update={"status": "not_comparable"})
    result.previous_observation_id = UUID(previous["id"])
    if datetime.fromisoformat(current["observed_at"].replace("Z", "+00:00")) <= datetime.fromisoformat(previous["observed_at"].replace("Z", "+00:00")):
        return result.model_copy(update={"status": "out_of_order"})
    with localcontext() as context:
        context.prec = 40
        old, new = Decimal(str(previous["price"])), Decimal(str(current["price"]))
        result.price_difference = new - old
        if old == 0:
            result.status = "unchanged" if new == 0 else "zero_baseline"
            return result
        result.percentage_change = (new - old) * Decimal(100) / old
        # Cross-multiplication keeps threshold classification exact.
        result.exceeds_threshold = abs(new - old) * Decimal(100) > old * threshold
        result.status = "unchanged" if new == old else "changed"
    return result


def observation_values(raw, match, observation_id):
    error = raw.error
    price = raw.price
    status = raw.status
    # Never silently round the supplied numeric(14,2) column.
    if price is not None:
        try:
            with localcontext() as context:
                context.prec = 40
                if price > Decimal("999999999999.99") or price != price.quantize(Decimal("0.01")):
                    raise ValueError()
        except (InvalidOperation, ValueError):
            price, status = None, "partial"
            error = "Extracted price cannot be represented exactly by numeric(14,2)"
    currency = raw.currency.upper() if raw.currency else None
    if currency and not re.fullmatch(r"[A-Z]{3}", currency):
        currency, status = None, "partial"
        error = "Extracted currency is not a three-letter currency code"
    return {
        "id": str(observation_id), "price": str(price) if price is not None else None,
        "currency": currency, "availability": raw.availability,
        "extraction_status": status, "source_url": raw.source_url,
        "observed_at": raw.observed_at.isoformat(), "matching_status": match,
        "extraction_error": error,
        "extracted_product": raw.model_dump(mode="json"),
    }


def record_observation(repository: Repository, listing_id, observation_id) -> RecordResult:
    threshold, atomic = settings()
    listing = repository.get("competitor_listings", listing_id)
    product = repository.get("products", listing["product_id"])
    existing = repository.existing_observation(observation_id, listing_id)
    if existing:
        return RecordResult(observation=existing, change=ChangeResult(status="replayed", threshold_percent=threshold),
                            alert_status="not_reprocessed", replayed=True)
    if not listing["is_active"]:
        raise HTTPException(409, "Competitor listing is inactive")
    raw, _ = extract_product(listing["product_url"])
    reference = CompareRequest(product_name=product["name"], selling_price=product["selling_price"],
                               currency=product["currency"], brand=product.get("brand"),
                               sku=product.get("sku"), model_number=product.get("model_number"),
                               competitor_urls=[listing["product_url"]])
    match, _ = identity(reference, raw)
    values = observation_values(raw, match, observation_id)
    values["listing_id"] = str(listing_id)
    if not atomic:
        # Existing schema cannot persist identity evidence or atomically dedupe alerts.
        basic = {key: value for key, value in values.items()
                 if key not in ("matching_status", "extraction_error", "extracted_product")}
        try:
            saved = repository.insert("price_observations", basic)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            saved = repository.existing_observation(observation_id, listing_id)
            if saved is None:
                raise
            return RecordResult(observation=saved, change=ChangeResult(status="replayed", threshold_percent=threshold),
                                alert_status="not_reprocessed", replayed=True)
        # Error is returned to the caller but cannot be stored with the old schema.
        saved = {**saved, "extraction_error": values["extraction_error"]}
        return RecordResult(observation=saved,
                            change=ChangeResult(status="migration_required", threshold_percent=threshold),
                            alert_status="migration_required")
    # Retry only the database baseline calculation, never the Context.dev request.
    for _ in range(3):
        previous = repository.previous_valid(listing_id, values["currency"]) if values["currency"] else None
        change = detect_change(previous, values, threshold)
        alert = None
        if change.exceeds_threshold:
            alert = {
                "event_type": "competitor_price_change", "severity": "medium",
                "title": "Competitor price changed",
                "description": "Confirmed competitor price change exceeded the configured percentage threshold",
                "old_price": str(previous["price"]), "new_price": values["price"],
                "currency": values["currency"], "source_url": values["source_url"],
            }
        result = repository.record_atomic(listing_id, values, str(previous["id"]) if previous else None, alert)
        if result is not None:
            if result.get("replayed", False):
                return RecordResult(observation=result["observation"], alert=result.get("alert"),
                                    change=ChangeResult(status="replayed", threshold_percent=threshold),
                                    alert_status="not_reprocessed", replayed=True)
            return RecordResult(observation=result["observation"], alert=result.get("alert"), change=change,
                                alert_status="created" if result.get("alert") else "not_triggered",
                                replayed=False)
    raise HTTPException(409, "Concurrent observation updates; retry with the same Idempotency-Key")
