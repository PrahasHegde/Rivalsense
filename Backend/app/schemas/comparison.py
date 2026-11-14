"""Comparison contracts. Decimal money serializes as JSON strings."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, Field, StringConstraints, field_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=20, decimal_places=6)]


class CompareRequest(BaseModel):
    product_name: Text
    selling_price: Money
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    sku: Text | None = None
    model_number: Text | None = None
    brand: Text | None = None
    # Validate destinations individually so unsafe inputs don't discard good results.
    competitor_urls: list[Annotated[str, Field(min_length=1, max_length=2083)]] = Field(min_length=1, max_length=5)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("selling_price", mode="before")
    @classmethod
    def reject_boolean_price(cls, value):
        if isinstance(value, bool):
            raise ValueError("Selling price must be a nonnegative monetary amount")
        return value


class CompetitorResult(BaseModel):
    requested_url: str
    source_url: str
    observed_at: datetime
    extraction_status: Literal["success", "partial", "failure"]
    extraction_http_status: int
    extraction_error: str | None = None
    product_name: str | None = None
    brand: str | None = None
    sku: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    availability: str | None = None
    matching_status: Literal["confirmed", "needs_review", "mismatch", "unavailable"]
    matching_reason: str
    comparable: bool = False
    comparison_reason: str
    price_difference: Decimal | None = None


class CompareResponse(BaseModel):
    status: Literal["success", "partial", "failure"]
    product_name: str
    selling_price: Decimal
    currency: str
    observed_at: datetime
    competitors: list[CompetitorResult]
    comparable_count: int
    lowest_competitor_price: Decimal | None = None
    lowest_competitor_source_urls: list[str] = Field(default_factory=list)
