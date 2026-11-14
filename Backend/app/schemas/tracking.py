"""Contracts matching the supplied public table definitions."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from app.schemas.comparison import Text
from app.schemas.prices import ExtractRequest

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Text
    brand: Text | None = None
    sku: Text | None = None
    model_number: Text | None = None
    selling_price: Money
    cost_price: Money | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("selling_price", "cost_price", mode="before")
    @classmethod
    def no_boolean_money(cls, value):
        if isinstance(value, bool):
            raise ValueError("Price must be a monetary amount")
        return value


class ProductRow(ProductCreate):
    id: UUID
    user_id: UUID
    created_at: datetime
    is_archived: bool = False


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_archived: bool


class ListingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool


class ListingCreate(ExtractRequest):
    # Reuse the HTTPS validator, with the database's product_url field name.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    url: HttpUrl = Field(alias="product_url")
    competitor_name: Text


class ListingRow(BaseModel):
    id: UUID
    user_id: UUID
    product_id: UUID
    competitor_name: str
    product_url: str
    is_active: bool
    created_at: datetime


class ObservationRow(BaseModel):
    id: UUID
    user_id: UUID
    listing_id: UUID
    price: Money | None = None
    currency: str | None = None
    availability: str | None = None
    extraction_status: Literal["success", "partial", "failure"]
    source_url: str
    observed_at: datetime
    matching_status: str = "needs_review"
    extraction_error: str | None = None
    extracted_product: dict | None = None
    capture_event_id: UUID | None = None


class AlertRow(BaseModel):
    id: UUID
    user_id: UUID
    product_id: UUID
    event_type: str
    severity: str
    title: str
    description: str | None = None
    old_price: Money | None = None
    new_price: Money | None = None
    currency: str | None = None
    source_url: str | None = None
    status: str
    created_at: datetime
    source_observation_id: UUID | None = None


class ChangeResult(BaseModel):
    status: str
    previous_observation_id: UUID | None = None
    price_difference: Decimal | None = None
    percentage_change: Decimal | None = None
    threshold_percent: Decimal
    exceeds_threshold: bool = False


class RecordResult(BaseModel):
    observation: ObservationRow
    change: ChangeResult
    alert: AlertRow | None = None
    alert_status: str
    replayed: bool = False
