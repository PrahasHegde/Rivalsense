"""Extraction and comparison HTTP endpoints."""
from typing import Annotated
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.schemas.prices import ExtractRequest, ExtractResponse
from app.schemas.comparison import CompareRequest, CompareResponse
from app.services.extraction import extract_product
from app.services.comparison import compare_prices
from app.core.auth import UserDatabase, get_user_database
from app.services.database import Repository
from app.services.rate_limit import extraction_budget

router = APIRouter(prefix="/api/prices", tags=["prices"])
Session = Annotated[UserDatabase, Depends(get_user_database)]


@router.post("/extract", response_model=ExtractResponse,
             responses={400: {}, 422: {}, 502: {}, 503: {}, 504: {}})
def extract_price(request: ExtractRequest, session: Session):
    with extraction_budget(Repository(session)):
        observation, status_code = extract_product(str(request.url))
    result = ExtractResponse.model_validate(observation.model_dump())
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=result.model_dump(mode="json"))
    return result


@router.post("/compare", response_model=CompareResponse)
def compare_price(request: CompareRequest, session: Session):
    with extraction_budget(Repository(session), units=len(request.competitor_urls)):
        return compare_prices(request)
