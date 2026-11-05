"""/ai/chats (private AI Chat history) and /documents (the manager's knowledge base).

Chats belong to one user only: another user's chat id is "not found", even for a
manager. Documents marked ``managers`` are never returned to employees.
"""
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select

from app.core.deps import CurrentManager, CurrentUser
from app.db.models import AIChat, AIMessage, Document
from app.repositories.tenant import AIChatRepository, AIMessageRepository, DocumentRepository
from app.routers.common import NOT_FOUND

router = APIRouter(tags=["content"])


# ---------------------------------------------------------------- AI chats
class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class ChatOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message: str | None = None


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=50000)]
    source: Literal["engine", "llm"] | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    chat_id: uuid.UUID
    role: str
    content: str
    source: str | None
    created_at: datetime


def _own_chat(principal, chat_id) -> AIChat:
    chat = AIChatRepository(principal.session, principal.company_id).get(chat_id)
    if chat is None or chat.user_id != principal.user.id:
        raise NOT_FOUND
    return chat


def _chat_out(chat: AIChat, count=0, last=None) -> ChatOut:
    return ChatOut(id=chat.id, user_id=chat.user_id, title=chat.title, created_at=chat.created_at,
                   updated_at=chat.updated_at, message_count=count, last_message=last)


@router.get("/ai/chats", response_model=list[ChatOut])
def list_chats(principal: CurrentUser):
    chats = AIChatRepository(principal.session, principal.company_id).list(
        AIChat.user_id == principal.user.id, order_by=AIChat.updated_at.desc())
    if not chats:
        return []
    ids = [c.id for c in chats]
    counts = dict(principal.session.execute(
        select(AIMessage.chat_id, func.count()).where(AIMessage.company_id == principal.company_id,
                                                      AIMessage.chat_id.in_(ids)).group_by(AIMessage.chat_id)).all())
    ranked = (select(AIMessage.chat_id, AIMessage.content,
                     func.row_number().over(partition_by=AIMessage.chat_id, order_by=AIMessage.id.desc()).label("n"))
              .where(AIMessage.company_id == principal.company_id, AIMessage.chat_id.in_(ids)).subquery())
    last = {r.chat_id: r.content for r in principal.session.execute(select(ranked).where(ranked.c.n == 1))}
    return [_chat_out(c, counts.get(c.id, 0), last.get(c.id)) for c in chats]


@router.post("/ai/chats", response_model=ChatOut, status_code=status.HTTP_201_CREATED)
def create_chat(body: ChatIn, principal: CurrentUser):
    return _chat_out(AIChatRepository(principal.session, principal.company_id).add(
        user_id=principal.user.id, title=body.title or None))


@router.get("/ai/chats/{chat_id}", response_model=ChatOut)
def get_chat(chat_id: uuid.UUID, principal: CurrentUser):
    return _chat_out(_own_chat(principal, chat_id))


@router.patch("/ai/chats/{chat_id}", response_model=ChatOut)
def rename_chat(chat_id: uuid.UUID, body: ChatIn, principal: CurrentUser):
    chat = _own_chat(principal, chat_id)
    return _chat_out(AIChatRepository(principal.session, principal.company_id).update(chat, title=body.title or None))


@router.delete("/ai/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(chat_id: uuid.UUID, principal: CurrentUser):
    AIChatRepository(principal.session, principal.company_id).delete(_own_chat(principal, chat_id))


@router.post("/ai/chats/{chat_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def add_message(chat_id: uuid.UUID, body: MessageIn, principal: CurrentUser):
    chat = _own_chat(principal, chat_id)
    message = AIMessageRepository(principal.session, principal.company_id).add(
        chat_id=chat.id, role=body.role, content=body.content, source=body.source)
    AIChatRepository(principal.session, principal.company_id).update(chat, updated_at=datetime.now(UTC))
    return message


@router.get("/ai/chats/{chat_id}/messages", response_model=list[MessageOut])
def list_messages(chat_id: uuid.UUID, principal: CurrentUser, limit: int | None = Query(None, ge=1, le=2000)):
    _own_chat(principal, chat_id)
    messages = AIMessageRepository(principal.session, principal.company_id)
    statement = messages.query().where(AIMessage.chat_id == chat_id)
    if limit:
        rows = list(principal.session.scalars(statement.order_by(AIMessage.id.desc()).limit(limit)))
        return rows[::-1]
    return list(principal.session.scalars(statement.order_by(AIMessage.id)))


# ---------------------------------------------------------------- documents
class DocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    content: Annotated[str, Field(max_length=2_000_000)]
    visibility: Literal["everyone", "managers"] = "everyone"


class VisibilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visibility: Literal["everyone", "managers"]


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    visibility: str
    uploaded_by: uuid.UUID | None
    size: int
    words: int
    created_at: datetime
    updated_at: datetime
    content: str | None = None
    created: bool | None = None


def _doc_out(doc: Document, with_content=False, created=None) -> DocumentOut:
    return DocumentOut(id=doc.id, filename=doc.filename, visibility=doc.visibility, uploaded_by=doc.uploaded_by,
                       size=doc.size, words=doc.words, created_at=doc.created_at, updated_at=doc.updated_at,
                       content=doc.content if with_content else None, created=created)


def _documents(principal):
    query = DocumentRepository(principal.session, principal.company_id).query()
    if not principal.is_manager:
        query = query.where(Document.visibility == "everyone")
    return query


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(principal: CurrentUser, with_content: bool = False, include_managers: bool = True):
    query = _documents(principal)
    if not include_managers:
        query = query.where(Document.visibility == "everyone")
    docs = principal.session.scalars(query.order_by(func.lower(Document.filename)))
    return [_doc_out(d, with_content) for d in docs]


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: uuid.UUID, principal: CurrentUser):
    doc = principal.session.scalars(_documents(principal).where(Document.id == doc_id)).first()
    if doc is None:
        raise NOT_FOUND
    return _doc_out(doc, with_content=True)


@router.put("/documents", response_model=DocumentOut)
def upsert_document(body: DocumentIn, principal: CurrentManager):
    """Add a document, or replace the one with the same file name."""
    docs = DocumentRepository(principal.session, principal.company_id)
    existing = principal.session.scalars(
        docs.query().where(func.lower(Document.filename) == body.filename.lower())).first()
    values = {"content": body.content, "visibility": body.visibility, "uploaded_by": principal.user.id,
              "size": len(body.content.encode("utf-8")), "words": len(body.content.split())}
    if existing:
        return _doc_out(docs.update(existing, updated_at=datetime.now(UTC), **values), created=False)
    return _doc_out(docs.add(filename=body.filename, **values), created=True)


@router.patch("/documents/{doc_id}", response_model=DocumentOut)
def set_visibility(doc_id: uuid.UUID, body: VisibilityIn, principal: CurrentManager):
    docs = DocumentRepository(principal.session, principal.company_id)
    doc = docs.get(doc_id)
    if doc is None:
        raise NOT_FOUND
    return _doc_out(docs.update(doc, visibility=body.visibility, updated_at=datetime.now(UTC)))


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: uuid.UUID, principal: CurrentManager):
    docs = DocumentRepository(principal.session, principal.company_id)
    doc = docs.get(doc_id)
    if doc is None:
        raise NOT_FOUND
    docs.delete(doc)
