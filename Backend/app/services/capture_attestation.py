"""Exact UTF-8 signed evidence produced only from backend extraction."""
import hashlib
import hmac
import json
import re
from decimal import Decimal, InvalidOperation, localcontext

from app.schemas.comparison import CompareRequest
from app.services.comparison import identity


def capture_payload(user_id, event_id, listing, product, observation):
    """event_id is a stable backend capture receipt, never a new row UUID per retry."""
    reference = {key: product.get(key) for key in ("name", "brand", "sku", "model_number")}
    request = CompareRequest(product_name=product["name"], selling_price=product["selling_price"],
                             currency=product["currency"], brand=product.get("brand"),
                             sku=product.get("sku"), model_number=product.get("model_number"),
                             competitor_urls=[listing["product_url"]])
    status, reason = identity(request, observation)
    bases = {"Exact normalized name and SKU match": "name_and_sku",
             "Exact normalized name and explicit model number match": "name_and_model",
             "Exact normalized name and brand match": "name_and_brand"}
    normalized = normalize_observation(observation)
    return {"version": 1, "action": "record", "user_id": str(user_id), "capture_event_id": str(event_id),
            "listing_id": str(listing["id"]), "product_url": listing["product_url"],
            "observation": {key: value for key, value in normalized.model_dump(mode="json").items()
                            if key in ("price", "currency", "availability", "source_url", "observed_at")}
                           | {"extraction_status": normalized.status, "extraction_error": normalized.error},
            "evidence": {"validator": "rivalsense-identity-v1", "reference": reference,
                         "extracted": observation.model_dump(mode="json"), "matching_status": status,
                         "basis": bases.get(reason), "reason": reason}}


def normalize_observation(observation):
    values = {}
    if observation.price is not None:
        try:
            with localcontext() as context:
                context.prec = 40
                if (not observation.price.is_finite() or observation.price < 0
                        or observation.price > Decimal("999999999999.99")
                        or observation.price != observation.price.quantize(Decimal("0.01"))):
                    raise ValueError()
        except (ValueError, InvalidOperation):
            values.update(price=None, status="partial", error="Extracted price cannot be represented exactly by numeric(14,2)")
    currency = observation.currency.upper() if observation.currency else None
    if currency and not re.fullmatch(r"[A-Z]{3}", currency):
        currency = None
        values.update(status="partial", error="Extracted currency is not a three-letter currency code")
    return observation.model_copy(update={**values, "currency": currency})


def sign_capture(payload, secret):
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("A privately provisioned recording secret is required")
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    signature = hmac.new(secret.encode(), serialized.encode(), hashlib.sha256).hexdigest()
    return serialized, signature


def verify_capture(serialized, signature, secret):
    expected = hmac.new(secret.encode(), serialized.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
