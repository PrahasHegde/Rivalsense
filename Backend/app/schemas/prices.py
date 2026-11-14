"""Request and response contract for the frontend."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator


class ExtractRequest(BaseModel):
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def https_only(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.username or value.password or value.port != 443:
            raise ValueError("Use public HTTPS on port 443 without credentials")
        return value


class ExtractResponse(BaseModel):
    status: Literal["success", "partial", "failure"]
    product_name: str | None = None
    brand: str | None = None
    price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = None
    availability: str | None = None
    source_url: str
    observed_at: datetime
    error: str | None = None
