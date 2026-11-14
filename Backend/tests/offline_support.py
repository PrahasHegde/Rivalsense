"""Fixtures and explicit dependency overrides for existing extraction regressions."""
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from app.core.auth import UserDatabase, get_user_database
from app.main import app
from app.services.extraction import ProductObservation

USER_A, USER_B, PRODUCT, LISTING = [str(uuid4()) for _ in range(4)]
URL = "https://shop.example.com/mug"
NOW = "2026-11-14T12:00:00+00:00"


def product():
    return dict(id=PRODUCT, user_id=USER_A, name="Acme Mug M-100", brand="Acme", sku="M-100",
                model_number="M-100", selling_price="120.00", cost_price=None, currency="EUR",
                created_at=NOW, is_archived=False)


def listing():
    return dict(id=LISTING, user_id=USER_A, product_id=PRODUCT, competitor_name="Shop",
                product_url=URL, is_active=True, created_at=NOW)


def raw():
    return ProductObservation(status="success", product_name="Acme Mug M-100", brand="Acme",
                              sku="M-100", price=Decimal("110.00"), currency="EUR",
                              availability="in_stock", source_url=URL, observed_at=datetime.now(timezone.utc))


def observation(price="100.00", **changes):
    return dict(id=str(uuid4()), user_id=USER_A, listing_id=LISTING, price=price, currency="EUR",
                availability="in_stock", source_url=URL, extraction_status="success", observed_at=NOW,
                matching_status="confirmed", **changes)


def authorize_functional_tests(test):
    app.dependency_overrides[get_user_database] = lambda: UserDatabase(USER_A, None)
    test.addCleanup(lambda: app.dependency_overrides.pop(get_user_database, None))
    budget = patch("app.api.prices.extraction_budget", side_effect=lambda *args, **kwargs: nullcontext())
    budget.start()
    test.addCleanup(budget.stop)
