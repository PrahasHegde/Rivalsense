"""Basic service information and health endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def root() -> dict[str, str]:
    return {"message": "Welcome to MarginGuard API", "version": "0.1.0"}


@router.get("/health")
def health() -> dict[str, str]:
    # This checks the API only; external services are not connected yet.
    return {"status": "ok"}
