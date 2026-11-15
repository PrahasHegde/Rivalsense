"""Service health check; does not contact or mutate external services."""
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
