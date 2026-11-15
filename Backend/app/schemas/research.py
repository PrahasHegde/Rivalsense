"""Sourced research contracts; missing metadata stays unknown."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=2000)

class ResearchSource(BaseModel):
    title: str
    url: str
    publisher: str | None = None
    published_at: str | None = None

class ResearchFact(BaseModel):
    label: str
    value: str
    source_url: str | None = None

class AskResponse(BaseModel):
    question: str
    answer: str
    keywords: list[str] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    research_data: dict = Field(default_factory=dict)
    status: Literal["completed", "partial", "insufficient_evidence"]
    retrieved_at: datetime
    persistence: Literal["not_configured", "saved", "unavailable"] = "not_configured"
