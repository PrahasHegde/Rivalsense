"""Server-side wrapper around the official Context.dev SDK."""
import os
from context.dev import ContextDev
from app.core import config  # Load the project's .env before reading settings.


class MissingAPIKey(RuntimeError):
    pass


def require_api_key() -> str:
    key = os.getenv("CONTEXT_DEV_API_KEY", "").strip()
    if not key:
        raise MissingAPIKey()
    return key


def scrape_product(url: str):
    # Never log or forward raw provider responses or exceptions.
    with ContextDev(api_key=require_api_key(), timeout=60.0, max_retries=0) as client:
        return client.web.scrape(
            url=url,
            formats={"product": True},
            product_params={"dedupe_images": False},
            max_age_ms=0,
            timeout_opts={"milliseconds": 55000, "behavior": "return-partial"},
            zdr="disabled",
        )
