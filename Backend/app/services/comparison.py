"""Conservative identity checks and Decimal calculations; no recommendations."""
from datetime import datetime, timezone
from decimal import localcontext
import re
import unicodedata
from app.schemas.comparison import CompareRequest, CompareResponse, CompetitorResult
from app.services.extraction import ProductObservation, extract_product


def normalized(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    # Preserve punctuation: model AB-12 differs from AB12; 1.5 differs from 1-5.
    return " ".join(value.split())


def identity(request: CompareRequest, product: ProductObservation) -> tuple[str, str]:
    if product.status == "failure":
        return "unavailable", "Extraction failed"
    name_matches = normalized(request.product_name) == normalized(product.product_name)
    if request.brand and product.brand and normalized(request.brand) != normalized(product.brand):
        return "mismatch", "Reported brands differ"
    if request.sku and product.sku and normalized(request.sku) != normalized(product.sku):
        return "needs_review", "SKUs differ; retailer SKU namespaces may differ"
    if request.model_number:
        model = normalized(request.model_number)
        if not re.search(r"(?<![\w./-])" + re.escape(model) + r"(?![\w./-])", normalized(product.product_name)):
            return "needs_review", "Requested model number is not explicit in the extracted name"
    if not name_matches:
        return "needs_review", "Product names differ or are missing; verify model and variant"
    if request.sku and product.sku and normalized(request.sku) == normalized(product.sku):
        return "confirmed", "Exact normalized name and SKU match"
    if request.model_number:
        return "confirmed", "Exact normalized name and explicit model number match"
    if request.brand and product.brand and normalized(request.brand) == normalized(product.brand):
        return "confirmed", "Exact normalized name and brand match"
    return "needs_review", "Name alone is insufficient to confirm product identity"


def compare_prices(request: CompareRequest) -> CompareResponse:
    results = []
    for url in request.competitor_urls:
        observation, http_status = extract_product(url)
        match, match_reason = identity(request, observation)
        comparable = False
        difference = None
        if observation.status == "failure":
            reason = "Extraction failed"
        elif match != "confirmed":
            reason = "Product identity requires confirmation"
        elif observation.price is None:
            reason = "Competitor price is unknown"
        elif not observation.currency or observation.currency.upper() != request.currency:
            reason = "Currency differs or is unknown; no currency conversion performed"
        else:
            comparable = True
            reason = "Confirmed product with the same currency"
            with localcontext() as context:
                prices = (request.selling_price, observation.price)
                context.prec = max(p.adjusted() for p in prices) - min(p.as_tuple().exponent for p in prices) + 3
                difference = request.selling_price - observation.price
        results.append(CompetitorResult(
            requested_url=url, source_url=observation.source_url, observed_at=observation.observed_at,
            extraction_status=observation.status, extraction_http_status=http_status,
            extraction_error=observation.error, product_name=observation.product_name,
            brand=observation.brand, sku=observation.sku, price=observation.price,
            currency=observation.currency, availability=observation.availability,
            matching_status=match, matching_reason=match_reason, comparable=comparable,
            comparison_reason=reason, price_difference=difference))
    valid = [item for item in results if item.comparable]
    lowest = min((item.price for item in valid), default=None)
    if all(item.extraction_status == "failure" for item in results):
        status = "failure"
    elif all(item.comparable and item.extraction_status == "success" for item in results):
        status = "success"
    else:
        status = "partial"
    return CompareResponse(
        status=status, product_name=request.product_name, selling_price=request.selling_price,
        currency=request.currency, observed_at=datetime.now(timezone.utc), competitors=results,
        comparable_count=len(valid), lowest_competitor_price=lowest,
        lowest_competitor_source_urls=[item.source_url for item in valid if item.price == lowest])
