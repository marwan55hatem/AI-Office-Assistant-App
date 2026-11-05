"""/ai/chat and /ai/status: general and document questions answered by the online model.

The desktop app decides (with its intent engine) whether a question is about the
user's own data; only the other questions come here. The server then builds the
prompt itself -- fixed instruction, the model's own earlier answers in this chat,
passages from the company's documents this user may read -- so neither the app nor a
modified client can add database contents or another company's text to it.

The answer is streamed as server-sent events:
    data: {"type": "delta", "text": "..."}       (many)
    data: {"type": "done", "sources": [...]}     (last, on success)
    data: {"type": "error", "message": "..."}    (last, on failure)
"""
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.ai.bm25 import BM25Index
from app.ai.prompts import build_messages
from app.ai.provider import ModelUnavailable, Usage, get_chat_model
from app.ai.text import split_document
from app.core.config import get_settings
from app.core.deps import CurrentUser, UNAUTHORIZED, _bearer
from app.core.ratelimit import login_limiter
from app.core.security import ACCESS, TokenError, decode_token
from app.db.models import AIMessage, AIUsage, Document
from app.db.session import transaction
from app.repositories.tenant import AIChatRepository, AIMessageRepository, DocumentRepository, UserRepository

router = APIRouter(prefix="/ai", tags=["ai"])

BUDGET_MESSAGE = "Your company has used today's AI allowance. It resets at midnight UTC."


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_id: uuid.UUID
    question: Annotated[str, Field(min_length=1, max_length=4000)]


class StatusOut(BaseModel):
    available: bool
    model: str | None
    provider: str
    daily_token_budget: int
    tokens_used_today: int
    provider_log_days: int
    sent_to_model: list[str]
    never_sent: list[str]


SENT = ["your question", "the AI's own earlier answers in the same chat",
        "matching passages from your company's documents that you are allowed to read"]
NEVER_SENT = ["your tasks, deadlines and calendar", "work sessions, timers and team numbers",
              "camera images, screenshots and window titles", "other people's chats"]


def _today():
    return datetime.now(UTC).date()


def _tokens_used(session, company_id) -> int:
    row = session.scalars(select(AIUsage).where(AIUsage.company_id == company_id, AIUsage.day == _today())).first()
    return (row.tokens_in + row.tokens_out) if row else 0


def _record_usage(company_id, usage: Usage) -> None:
    with transaction(company_id) as session:
        statement = insert(AIUsage).values(company_id=company_id, day=_today(), requests=1,
                                           tokens_in=usage.prompt_tokens, tokens_out=usage.completion_tokens)
        session.execute(statement.on_conflict_do_update(
            index_elements=["company_id", "day"],
            set_={"requests": AIUsage.requests + 1, "tokens_in": AIUsage.tokens_in + usage.prompt_tokens,
                  "tokens_out": AIUsage.tokens_out + usage.completion_tokens}))


@router.get("/status", response_model=StatusOut)
def ai_status(principal: CurrentUser):
    settings = get_settings()
    model = get_chat_model()
    return StatusOut(available=model is not None, model=model.name if model else None, provider="Groq",
                     daily_token_budget=settings.ai_daily_token_budget,
                     tokens_used_today=_tokens_used(principal.session, principal.company_id),
                     provider_log_days=settings.ai_provider_log_days, sent_to_model=SENT, never_sent=NEVER_SENT)


def _history_pairs(session, company_id, chat_id, question, limit):
    """Earlier (question, answer) pairs of this chat that the model itself answered."""
    rows = session.scalars(AIMessageRepository(session, company_id).query()
                           .where(AIMessage.chat_id == chat_id).order_by(AIMessage.id)).all()
    if rows and rows[-1].role == "user" and rows[-1].content == question:
        rows = rows[:-1]                      # the new question, already stored by the app
    pairs, previous = [], None
    for row in rows:
        if row.role == "user":
            previous = row.content
        elif row.source == "llm" and previous is not None:
            pairs.append((previous, row.content))
            previous = None
        else:
            previous = None
    return pairs[-limit:]


def _passages(session, company_id, question, is_manager):
    query = DocumentRepository(session, company_id).query()
    if not is_manager:
        query = query.where(Document.visibility == "everyone")       # applied before searching
    chunks = []
    for doc in session.scalars(query):
        chunks += split_document(doc.id, doc.filename, doc.content)
    return BM25Index(chunks).search(question) if chunks else []


def _event(**data) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


@router.post("/chat")
def chat(body: ChatRequest,
         credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]):
    """Stream an answer. The database work finishes before streaming starts, so no
    transaction stays open while the model writes."""
    settings = get_settings()
    if credentials is None:
        raise UNAUTHORIZED
    try:
        claims = decode_token(credentials.credentials, ACCESS)
    except TokenError:
        raise UNAUTHORIZED from None
    company_id = claims["cid"]
    with transaction(company_id) as session:
        user = UserRepository(session, company_id).get(claims["sub"])
        if user is None or user.status != "active" or user.role != claims.get("role"):
            raise UNAUTHORIZED
        chat_row = AIChatRepository(session, company_id).get(body.chat_id)
        if chat_row is None or chat_row.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        if not login_limiter.hit(f"ai:{user.id}", settings.ai_requests_per_user_per_minute):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many questions at once. Please wait a moment.",
                                headers={"Retry-After": "60"})
        if _tokens_used(session, company_id) >= settings.ai_daily_token_budget:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, BUDGET_MESSAGE)
        model = get_chat_model()
        if model is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The online AI model is not set up on this server.")
        pairs = _history_pairs(session, company_id, chat_row.id, body.question, settings.ai_history_pairs)
        hits = _passages(session, company_id, body.question, user.role == "manager")
        messages = build_messages(pairs, body.question, hits)
        sources = list(dict.fromkeys(hit.filename for hit in hits))

    def events():
        usage = None
        try:
            for kind, value in model.stream(messages, settings.ai_max_output_tokens):
                if kind == "delta":
                    yield _event(type="delta", text=value)
                elif kind == "usage":
                    usage = value
            yield _event(type="done", sources=sources)
        except ModelUnavailable as error:
            yield _event(type="error", message=str(error), busy=error.busy)
        finally:
            # also when the user pressed Stop (the connection closes and this generator ends)
            if usage is not None:
                _record_usage(company_id, usage)
            else:
                _record_usage(company_id, Usage(sum(len(m["content"]) for m in messages) // 4, 0))

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
