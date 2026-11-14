"""Extraction and comparison HTTP endpoints."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.schemas.prices import ExtractRequest, ExtractResponse
from app.schemas.comparison import CompareRequest, CompareResponse
from app.services.extraction import extract_product
from app.services.comparison import compare_prices

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.post("/extract", response_model=ExtractResponse,
             responses={400: {}, 422: {}, 502: {}, 503: {}, 504: {}})
def extract_price(request: ExtractRequest):
    observation, status_code = extract_product(str(request.url))
    result = ExtractResponse.model_validate(observation.model_dump())
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=result.model_dump(mode="json"))
    return result


@router.post("/compare", response_model=CompareResponse)
def compare_price(request: CompareRequest):
    return compare_prices(request)
