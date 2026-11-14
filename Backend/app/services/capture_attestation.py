"""Proposed signed-recording contract; not wired into live recording yet."""
import hashlib
import hmac
import json

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
    return {"version": 1, "user_id": str(user_id), "capture_event_id": str(event_id),
            "listing_id": str(listing["id"]), "product_url": listing["product_url"],
            "observation": {key: value for key, value in observation.model_dump(mode="json").items()
                            if key in ("price", "currency", "availability", "source_url", "observed_at")}
                           | {"extraction_status": observation.status, "extraction_error": observation.error},
            "evidence": {"validator": "rivalsense-identity-v1", "reference": reference,
                         "extracted": observation.model_dump(mode="json"), "matching_status": status,
                         "basis": bases.get(reason), "reason": reason}}


def sign_capture(payload, secret):
    if len(secret) < 32:
        raise ValueError("A privately provisioned recording secret is required")
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    signature = hmac.new(secret.encode(), serialized.encode(), hashlib.sha256).hexdigest()
    return serialized, signature


def verify_capture(serialized, signature, secret):
    expected = hmac.new(secret.encode(), serialized.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
