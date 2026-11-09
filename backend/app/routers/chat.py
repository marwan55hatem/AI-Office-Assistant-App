"""/chat: one private conversation per employee with the company's managers.

* A conversation is identified by the employee's id. The employee and every manager of
  the company take part; other employees cannot see it (404, like an unknown id).
* Messages are sent and read over HTTP (``POST /chat/{employee_id}/messages``, paged
  history). The WebSocket ``/chat/ws`` only delivers events live: ``message``, ``read``,
  ``delivered`` and ``typing``. A client that is not connected loses nothing: it catches
  up with ``GET .../messages?after_id=``.
* Delivered: the message reached a device of the other side (pushed to an open
  connection, or fetched over HTTP). Read: the other side opened the conversation.
  For an employee's message, any manager counts as "the other side".
* Limits: 4000 characters per message; at most 10 messages in 10 s and 60 per minute per user.
* A new message creates (or refreshes) one unread in-app notification per conversation,
  and queues an e-mail that is sent only if the message is still unread and the person is
  still offline 10 minutes later. The e-mail never contains the message text.
"""
import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, case, func, select, update

from app.core.config import get_settings
from app.core.deps import CurrentUser
from app.core.ratelimit import RateLimiter
from app.core.security import ACCESS, TokenError, decode_token
from app.db.models import EmailLog, Message, Notification, User
from app.db.session import after_commit, transaction
from app.repositories.tenant import MessageRepository, NotificationRepository, UserRepository
from app.routers.common import NOT_FOUND
from app.services.chat_hub import hub
from app.services.email.outbox import queue_email

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_MESSAGE_CHARS = 4000
PREVIEW_CHARS = 120
burst_limiter = RateLimiter(window_seconds=10)
minute_limiter = RateLimiter(window_seconds=60)
BURST_LIMIT, MINUTE_LIMIT = 10, 60
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS * 2)]


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    up_to_id: int


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: uuid.UUID
    sender_id: uuid.UUID
    body: str
    created_at: datetime
    delivered_at: datetime | None
    read_at: datetime | None
    sender_name: str = ""


class Page(BaseModel):
    messages: list[MessageOut]
    has_more: bool


class Conversation(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    employee_status: str
    unread: int
    last_message: MessageOut | None


# ---------------------------------------------------------------- helpers
def _conversation_user(principal, employee_id: uuid.UUID) -> User:
    """The conversation's employee, if the caller may see it (else 404)."""
    if not principal.is_manager and employee_id != principal.user.id:
        raise NOT_FOUND
    employee = UserRepository(principal.session, principal.company_id).get(employee_id)
    if employee is None or employee.role != "employee":
        raise NOT_FOUND
    return employee


def _managers(session, company_id) -> list[User]:
    return UserRepository(session, company_id).list(User.role == "manager", User.status == "active")


def _participants(session, company_id, employee: User) -> list[uuid.UUID]:
    return [employee.id] + [m.id for m in _managers(session, company_id)]


def _from_other_side(principal, employee_id):
    """Messages written by the other side of the conversation, from the caller's point of view."""
    if principal.is_manager:
        return Message.sender_id == employee_id
    return Message.sender_id != employee_id


def _event(kind: str, **data) -> dict:
    return {"type": kind, **data}


def _named(session, company_id, messages) -> list[MessageOut]:
    """Messages with their sender's name (an employee cannot list the managers themselves)."""
    ids = {m.sender_id for m in messages}
    users = UserRepository(session, company_id)
    names = {u.id: u.full_name for u in users.list(User.id.in_(ids))} if ids else {}
    return [MessageOut.model_validate(m).model_copy(update={"sender_name": names.get(m.sender_id, "")})
            for m in messages]


def _push_after_commit(principal, user_ids, event: dict) -> None:
    after_commit(principal.session, lambda: hub.publish(principal.company_id, user_ids, event))


def _clean(body: str) -> str:
    text = _CONTROL.sub("", body.replace("\r\n", "\n")).strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The message is empty")
    if len(text) > MAX_MESSAGE_CHARS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"A message can have at most {MAX_MESSAGE_CHARS} characters")
    return text


# ---------------------------------------------------------------- reading
@router.get("/conversations", response_model=list[Conversation])
def conversations(principal: CurrentUser):
    """Managers: every employee's conversation -- unread ones first, then the most recent.
    Employees: their own one."""
    session, cid = principal.session, principal.company_id
    users = UserRepository(session, cid)
    if principal.is_manager:
        employees = users.list(User.role == "employee", User.status.in_(("active", "disabled")))
    else:
        employees = [principal.user]
    if not employees:
        return []
    ids = [e.id for e in employees]
    other_side = Message.sender_id == Message.employee_id if principal.is_manager else \
        Message.sender_id != Message.employee_id
    stats = session.execute(
        select(Message.employee_id, func.max(Message.id),
               func.count().filter(and_(other_side, Message.read_at.is_(None))))
        .where(Message.company_id == cid, Message.employee_id.in_(ids)).group_by(Message.employee_id)).all()
    last_ids = {row[0]: row[1] for row in stats}
    unread = {row[0]: row[2] for row in stats}
    last = {m.employee_id: m for m in MessageRepository(session, cid).list(Message.id.in_(list(last_ids.values())))}
    named = {m.employee_id: m for m in _named(session, cid, list(last.values()))}
    result = [Conversation(employee_id=e.id, employee_name=e.full_name, employee_status=e.status,
                           unread=unread.get(e.id, 0), last_message=named.get(e.id))
              for e in employees if e.status == "active" or e.id in last]
    # unread conversations first, then the most recent, then by name
    result.sort(key=lambda c: (c.unread == 0, c.last_message is None,
                               -(c.last_message.id if c.last_message else 0), c.employee_name.lower()))
    return result


@router.get("/unread-count")
def unread_count(principal: CurrentUser) -> dict:
    other_side = Message.sender_id == Message.employee_id if principal.is_manager else \
        Message.sender_id != Message.employee_id
    query = select(func.count()).select_from(Message).where(
        Message.company_id == principal.company_id, other_side, Message.read_at.is_(None))
    if not principal.is_manager:
        query = query.where(Message.employee_id == principal.user.id)
    return {"unread": principal.session.scalar(query) or 0}


@router.get("/{employee_id}/messages", response_model=Page)
def messages(employee_id: uuid.UUID, principal: CurrentUser, before_id: int | None = None,
             after_id: int | None = None, limit: int = Query(50, ge=1, le=100)):
    """A page of the conversation, oldest first. Default: the latest ``limit`` messages;
    ``before_id``: older ones (scrolling up); ``after_id``: newer ones (catching up)."""
    employee = _conversation_user(principal, employee_id)
    repository = MessageRepository(principal.session, principal.company_id)
    query = repository.query().where(Message.employee_id == employee.id)
    if after_id is not None:
        rows = list(principal.session.scalars(query.where(Message.id > after_id).order_by(Message.id)
                                              .limit(limit + 1)))
        has_more = len(rows) > limit
        rows = rows[:limit]
    else:
        if before_id is not None:
            query = query.where(Message.id < before_id)
        rows = list(principal.session.scalars(query.order_by(Message.id.desc()).limit(limit + 1)))
        has_more = len(rows) > limit
        rows = list(reversed(rows[:limit]))
    _mark_delivered(principal, employee, [m for m in rows if m.delivered_at is None])
    return Page(messages=_named(principal.session, principal.company_id, rows), has_more=has_more)


def _mark_delivered(principal, employee: User, rows: list[Message]) -> None:
    """The caller fetched these: the other side's ones count as delivered now."""
    mine = (lambda m: m.sender_id != employee.id) if not principal.is_manager else \
        (lambda m: m.sender_id == employee.id)
    fresh = [m for m in rows if mine(m)]
    if not fresh:
        return
    now = datetime.now(UTC)
    for message in fresh:
        message.delivered_at = now
    principal.session.flush()
    _push_after_commit(principal, _participants(principal.session, principal.company_id, employee),
                       _event("delivered", employee_id=str(employee.id), message_ids=[m.id for m in fresh],
                              at=now.isoformat()))


# ---------------------------------------------------------------- writing
@router.post("/{employee_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def send(employee_id: uuid.UUID, body: MessageIn, principal: CurrentUser):
    employee = _conversation_user(principal, employee_id)
    if employee.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This employee's account is disabled")
    key = f"{principal.company_id}:{principal.user.id}"
    if not burst_limiter.hit(key, BURST_LIMIT) or not minute_limiter.hit(key, MINUTE_LIMIT):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You are sending messages too fast. Wait a moment.")
    text = _clean(body.body)
    session, cid = principal.session, principal.company_id
    participants = _participants(session, cid, employee)
    recipients = [uid for uid in participants if uid != principal.user.id
                  and (principal.is_manager is False or uid == employee.id)]
    online = any(hub.is_online(cid, uid) for uid in recipients)
    message = MessageRepository(session, cid).add(
        employee_id=employee.id, sender_id=principal.user.id, body=text,
        delivered_at=datetime.now(UTC) if online else None)
    _notify(principal, employee, recipients, message)
    [out] = _named(session, cid, [message])
    _push_after_commit(principal, participants, _event("message", message=out.model_dump(mode="json")))
    return out


def _notify(principal, employee: User, recipient_ids, message: Message) -> None:
    """One unread in-app notification per conversation and person, and a delayed e-mail."""
    session, cid = principal.session, principal.company_id
    users = UserRepository(session, cid)
    notifications = NotificationRepository(session, cid)
    link = f"chat:{employee.id}"
    settings = get_settings()
    for user_id in recipient_ids:
        user = users.get(user_id)
        if user is None or user.status != "active":
            continue
        existing = session.scalars(notifications.query().where(
            Notification.user_id == user.id, Notification.link == link, Notification.read_at.is_(None))).first()
        title = f"New message from {principal.user.full_name}"
        preview = message.body if len(message.body) <= PREVIEW_CHARS else message.body[:PREVIEW_CHARS - 1] + "…"
        if existing is None:
            notifications.add(user_id=user.id, kind="chat_message", title=title, body=preview, link=link)
        else:
            notifications.update(existing, title=title, body=preview)
        if hub.is_online(cid, user.id):
            continue
        queued = session.scalar(select(func.count()).select_from(EmailLog).where(
            EmailLog.company_id == cid, EmailLog.user_id == user.id, EmailLog.template == "chat_unread",
            EmailLog.status == "queued", EmailLog.payload["employee_id"].astext == str(employee.id)))
        if not queued:
            row = queue_email(session, cid, user, "chat_unread",
                              {"title": "", "who": principal.user.full_name, "employee_id": str(employee.id),
                               "message_id": message.id})
            if row.status == "queued":
                row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=settings.chat_email_delay_minutes)


@router.post("/{employee_id}/read")
def mark_read(employee_id: uuid.UUID, body: ReadIn, principal: CurrentUser) -> dict:
    """The caller has seen the conversation up to ``up_to_id``: the other side's messages are read."""
    employee = _conversation_user(principal, employee_id)
    session, cid = principal.session, principal.company_id
    now = datetime.now(UTC)
    ids = list(session.scalars(update(Message).where(
        Message.company_id == cid, Message.employee_id == employee.id, Message.id <= body.up_to_id,
        _from_other_side(principal, employee.id), Message.read_at.is_(None))
        .values(read_at=now, delivered_at=case((Message.delivered_at.is_(None), now), else_=Message.delivered_at))
        .returning(Message.id)))
    session.execute(update(Notification).where(
        Notification.company_id == cid, Notification.user_id == principal.user.id,
        Notification.link == f"chat:{employee.id}", Notification.read_at.is_(None)).values(read_at=now))
    if ids:
        _push_after_commit(principal, _participants(session, cid, employee),
                           _event("read", employee_id=str(employee.id), message_ids=sorted(ids),
                                  reader_id=str(principal.user.id), at=now.isoformat()))
    return {"read": len(ids)}


# ---------------------------------------------------------------- the live channel
AUTH_SECONDS = 10.0


def _authenticate(token: str):
    """(company_id, user_id, role, expires_at) for a valid access token of an active user, else None."""
    try:
        claims = decode_token(token, ACCESS)
    except TokenError:
        return None
    with transaction(claims["cid"]) as session:
        user = UserRepository(session, claims["cid"]).get(claims["sub"])
        if user is None or user.status != "active" or user.role != claims.get("role"):
            return None
        return uuid.UUID(str(claims["cid"])), user.id, user.role, float(claims["exp"])


def _typing_targets(company_id, user_id, role, employee_id) -> list | None:
    with transaction(company_id) as session:
        employee = UserRepository(session, company_id).get(employee_id)
        if employee is None or employee.role != "employee":
            return None
        if role != "manager" and employee.id != user_id:
            return None
        return [uid for uid in _participants(session, company_id, employee) if uid != user_id]


@router.websocket("/ws")
async def live(socket: WebSocket):
    """Authenticate with the first message ``{"type": "auth", "token": <access token>}``
    (never in the URL, which ends up in logs). The connection is closed when the token
    expires (code 4001); the client reconnects with a fresh one."""
    await socket.accept()
    try:
        first = await asyncio.wait_for(socket.receive_json(), timeout=AUTH_SECONDS)
    except (TimeoutError, WebSocketDisconnect, ValueError, KeyError):
        await _close(socket, 4003)
        return
    identity = None
    if isinstance(first, dict) and first.get("type") == "auth" and isinstance(first.get("token"), str):
        identity = await run_in_threadpool(_authenticate, first["token"])
    if identity is None:
        await _close(socket, 4003)
        return
    company_id, user_id, role, expires = identity
    hub.add(company_id, user_id, socket)
    try:
        await socket.send_json(_event("ready", user_id=str(user_id), role=role))
        while True:
            remaining = expires - datetime.now(UTC).timestamp()
            if remaining <= 0:
                await socket.send_json(_event("expired"))
                await _close(socket, 4001)
                return
            try:
                incoming = await asyncio.wait_for(socket.receive_json(), timeout=remaining)
            except TimeoutError:
                continue
            except ValueError:
                continue                                             # not JSON: ignored
            kind = incoming.get("type") if isinstance(incoming, dict) else None
            if kind == "ping":
                await socket.send_json(_event("pong"))
            elif kind == "typing":
                try:
                    employee_id = uuid.UUID(str(incoming.get("employee_id")))
                except ValueError:
                    continue
                targets = await run_in_threadpool(_typing_targets, company_id, user_id, role, employee_id)
                if targets:
                    hub.publish(company_id, targets, _event("typing", employee_id=str(employee_id),
                                                            user_id=str(user_id)))
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(company_id, user_id, socket)


async def _close(socket: WebSocket, code: int) -> None:
    try:
        await socket.close(code=code)
    except Exception:
        pass


def chat_email_skip_reason(session, row: EmailLog) -> str | None:
    """Checked by the e-mail worker just before sending a ``chat_unread`` e-mail."""
    if hub.is_online(row.company_id, row.user_id):
        return "the person is online"
    message = MessageRepository(session, row.company_id).get(row.payload.get("message_id"))
    if message is None or message.read_at is not None:
        return "the message was read"
    return None
