"""Create the FastAPI application and register middleware and routes."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.prices import router as prices_router
from app.api.tracking import router as tracking_router
from app.core.config import CORS_ORIGINS

app = FastAPI(title="RivalSense API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(prices_router)
app.include_router(tracking_router)
