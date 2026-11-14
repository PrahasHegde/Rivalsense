"""Authenticated, RLS-scoped product tracking and price history endpoints."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from app.core.auth import UserDatabase, get_user_database
from app.schemas.tracking import ProductCreate, ProductRow, ListingCreate, ListingRow, ObservationRow, AlertRow, RecordResult
from app.services.database import Repository
from app.services.history import record_observation
from app.services.url_safety import UnsafeURL, public_destination

router = APIRouter(prefix="/api", tags=["tracking"])
Session = Annotated[UserDatabase, Depends(get_user_database)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post("/products", response_model=ProductRow, status_code=201)
def add_product(body: ProductCreate, session: Session):
    return Repository(session).insert("products", body.model_dump(mode="json"))


@router.get("/products", response_model=list[ProductRow])
def products(session: Session, limit: Limit = 50, offset: Offset = 0):
    return Repository(session).list("products", limit, offset)


@router.get("/products/{product_id}", response_model=ProductRow)
def product(product_id: UUID, session: Session):
    return Repository(session).get("products", product_id)


@router.post("/products/{product_id}/competitors", response_model=ListingRow, status_code=201)
def add_listing(product_id: UUID, body: ListingCreate, session: Session):
    repository = Repository(session)
    repository.get("products", product_id)
    try:
        url, _ = public_destination(str(body.url))
    except UnsafeURL:
        raise HTTPException(400, "Unsafe competitor product URL") from None
    return repository.insert("competitor_listings", {
        "product_id": str(product_id), "competitor_name": body.competitor_name, "product_url": url})


@router.get("/products/{product_id}/competitors", response_model=list[ListingRow])
def listings(product_id: UUID, session: Session, limit: Limit = 50, offset: Offset = 0):
    repository = Repository(session)
    repository.get("products", product_id)
    return repository.list("competitor_listings", limit, offset, product_id=product_id)


@router.post("/competitors/{listing_id}/observations", response_model=RecordResult)
def observe(listing_id: UUID, session: Session,
            idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")]):
    return record_observation(Repository(session), listing_id, idempotency_key)


@router.get("/competitors/{listing_id}/observations", response_model=list[ObservationRow])
def history(listing_id: UUID, session: Session, limit: Limit = 50, offset: Offset = 0):
    repository = Repository(session)
    repository.get("competitor_listings", listing_id)
    return repository.list("price_observations", limit, offset, listing_id=listing_id)


@router.get("/alerts", response_model=list[AlertRow])
def alerts(session: Session, limit: Limit = 50, offset: Offset = 0):
    return Repository(session).list("alerts", limit, offset)
