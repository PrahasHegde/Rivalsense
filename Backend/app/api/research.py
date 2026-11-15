"""Authenticated general research; optional history has no schema requirement."""
import os
from typing import Annotated
from fastapi import APIRouter, Depends
from app.core.auth import UserDatabase, get_user_database
from app.schemas.research import AskRequest, AskResponse
from app.services.database import Repository
from app.services.read_budget import reading_budget
from app.services.research import ask, save_optional

router = APIRouter(prefix="/api/ai", tags=["research"])
Session = Annotated[UserDatabase, Depends(get_user_database)]

@router.post("/ask", response_model=AskResponse)
def ask_rivalsense(body: AskRequest, session: Session):
    repository = Repository(session)
    with reading_budget(repository):
        result = ask(body.question)
    return save_optional(repository, result)

@router.get("/history")
def research_history(session: Session):
    if os.getenv("RESEARCH_HISTORY_ENABLED", "false").lower() != "true":
        return {"items": [], "status": "not_configured"}
    return {"items": Repository(session).list("ai_responses", 20, 0), "status": "available"}
