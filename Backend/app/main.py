"""FastAPI API and, when configured, the production React bundle."""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.api.prices import router as prices_router
from app.api.tracking import router as tracking_router
from app.api.research import router as research_router
from app.core.config import CORS_ORIGINS
from app.core.frontend import ReactStaticFiles


def create_app(frontend_dir=None):
    application = FastAPI(title="RivalSense API", version="0.1.0")
    application.add_middleware(
        CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
        allow_methods=["*"], allow_headers=["*"],
    )
    application.include_router(router)
    application.include_router(prices_router)
    application.include_router(tracking_router)
    application.include_router(research_router)
    directory = frontend_dir if frontend_dir is not None else os.getenv("FRONTEND_DIST")
    if directory:
        directory = Path(directory).resolve()
        if not (directory / "index.html").is_file():
            raise RuntimeError("FRONTEND_DIST must contain the built React index.html")
        application.mount("/", ReactStaticFiles(directory=str(directory), html=True), name="frontend")
    else:
        @application.get("/")
        def api_info():
            return {"message": "Welcome to RivalSense API", "version": "0.1.0"}
    return application


app = create_app()
