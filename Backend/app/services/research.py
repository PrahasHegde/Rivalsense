"""Context.dev Answers integration. No substitute model or fabricated fallback."""
from datetime import datetime, timezone
import ipaddress
import os
from urllib.parse import urlsplit
from fastapi import HTTPException
from context.dev import APIError, APIStatusError, APITimeoutError
import httpx
from app.schemas.research import AskResponse, ResearchSource
from app.services.context_client import MissingAPIKey, research_question

def public_link(value):
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        url = urlsplit(value)
        host = url.hostname
        if url.scheme not in ("https", "http") or not host or url.username or url.password:
            return None
        if "." not in host or host.endswith((".local", ".internal", ".localhost")) or host == "localhost":
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None

def ask(question):
    try:
        response = research_question(question)
    except MissingAPIKey:
        raise HTTPException(503, "Context.dev is not configured on the server") from None
    except (APITimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "Research timed out. Try a more focused question.") from None
    except APIStatusError as exc:
        if exc.status_code in (401, 403):
            raise HTTPException(503, "Context.dev rejected the server credential or account permissions") from None
        if exc.status_code == 429:
            raise HTTPException(503, "Context.dev quota or account credits are unavailable") from None
        raise HTTPException(502, "Context.dev could not complete this research") from None
    except (APIError, httpx.HTTPError):
        raise HTTPException(502, "Cannot reach Context.dev. No substitute answer was generated.") from None
    content = getattr(response, "json_content", None)
    if not isinstance(content, dict):
        raise HTTPException(502, "Context.dev returned an invalid research format") from None
    links = list(dict.fromkeys(link for raw in (getattr(response, "sources", None) or []) if (link := public_link(raw))))[:30]
    sources = [ResearchSource(title=urlsplit(link).hostname, url=link) for link in links]
    answer = content.get("answer")
    usable = isinstance(answer, str) and bool(answer.strip()) and bool(sources)
    facts = []
    for fact in content.get("facts", []) if isinstance(content.get("facts"), list) else []:
        if isinstance(fact, dict) and isinstance(fact.get("label"), str) and isinstance(fact.get("value"), (str, int, float)) and not isinstance(fact.get("value"), bool):
            facts.append({"label": fact["label"][:300], "value": str(fact["value"])[:2000],
                          "source_url": fact.get("source_url") if fact.get("source_url") in links else None})
    uncertainties = [v[:1000] for v in content.get("uncertainties", []) if isinstance(v, str)] if isinstance(content.get("uncertainties"), list) else []
    keywords = [v[:100] for v in content.get("keywords", []) if isinstance(v, str) and v.strip()] if isinstance(content.get("keywords"), list) else []
    return AskResponse(question=question,
        answer=answer.strip() if usable else "The provider did not return an answer with usable public sources. Try a narrower question.",
        keywords=keywords[:10], sources=sources,
        research_data={"facts": facts[:20] if usable else [], "uncertainties": uncertainties[:10],
                       "evidence_note": "Sources contributed to provider research; they are not independent verification of every claim."},
        status=("partial" if getattr(response, "partial", False) else "completed") if usable else "insufficient_evidence",
        retrieved_at=datetime.now(timezone.utc))

def save_optional(repository, result):
    if os.getenv("RESEARCH_HISTORY_ENABLED", "false").lower() != "true":
        return result
    # Missing/unavailable optional storage must never discard an otherwise usable answer.
    try:
        repository.insert("ai_responses", {
            "question": result.question, "answer": result.answer, "keywords": result.keywords,
            "sources": [source.model_dump() for source in result.sources], "research_data": result.research_data,
            "status": result.status, "retrieved_at": result.retrieved_at.isoformat()})
        return result.model_copy(update={"persistence": "saved"})
    except HTTPException:
        return result.model_copy(update={"persistence": "unavailable"})
