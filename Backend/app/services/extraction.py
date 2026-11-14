"""Shared extraction workflow for extraction and comparison."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx
from context.dev import APIError, APITimeoutError, APIStatusError

from app.schemas.prices import ExtractResponse
from app.services.context_client import MissingAPIKey, require_api_key, scrape_product
from app.services.url_safety import UnsafeURL, check_redirects, public_destination

class ProductObservation(ExtractResponse):
    price: Decimal | None = None
    sku: str | None = None


def decimal_price(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


def extract_product(source: str) -> tuple[ProductObservation, int]:

    def failure(code: int, message: str):
        result = ProductObservation(status="failure", source_url=source,
                                 observed_at=datetime.now(timezone.utc), error=message)
        return result, code

    try:
        require_api_key()
        checked_url = check_redirects(source)
        page = scrape_product(checked_url)
        final_url = getattr(page, "url", None)
        if not isinstance(final_url, str) or not final_url:
            return failure(502, "Provider returned no source URL")
        public_destination(final_url)
        output = getattr(page, "product", None)
        data = getattr(output, "data", None)
        if getattr(output, "success", None) is not True or data is None:
            return failure(502, "Product extraction failed or returned no data")
        if getattr(data, "is_product_page", None) is False:
            return failure(422, "URL is not a product page")
        if getattr(data, "is_product_page", None) is not True:
            return failure(502, "Provider returned an invalid product result")
        product = getattr(data, "product", None)
        if product is None:
            return failure(502, "Product extraction returned no product")
        values = {}
        for field in ("name", "brand", "currency", "availability", "sku"):
            value = getattr(product, field, None)
            values["product_name" if field == "name" else field] = (value.strip() or None) if isinstance(value, str) else None
        values["price"] = decimal_price(getattr(product, "price", None))
        fields = ("product_name", "brand", "price", "currency", "availability")
        if all(values[field] is None for field in fields):
            return failure(502, "Product extraction returned no usable fields")
        partial = getattr(page, "is_partial", False) or any(values[field] is None for field in fields)
        return ProductObservation(status="partial" if partial else "success", source_url=final_url,
                                  observed_at=datetime.now(timezone.utc), **values), 200
    except UnsafeURL:
        return failure(400, "Unsafe URL or redirect destination")
    except MissingAPIKey:
        return failure(503, "Extraction service is not configured")
    except (APITimeoutError, httpx.TimeoutException):
        return failure(504, "Extraction timed out")
    except APIStatusError as exc:
        if exc.status_code in (408, 504):
            return failure(504, "Extraction timed out")
        if exc.status_code in (401, 403, 429):
            return failure(503, "Extraction provider is currently unavailable")
        return failure(502, "Extraction provider request failed")
    except (APIError, httpx.HTTPError):
        return failure(502, "Unable to retrieve or extract the product page")
