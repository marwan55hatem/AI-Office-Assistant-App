"""/sessions: the desktop app's work sessions, events and history.

The desktop app creates session and event ids itself, so it can record a session while
offline and send it later. ``POST /sessions/sync`` is idempotent: sending the same batch
twice stores it once, and counters only ever grow.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.core.deps import CurrentUser
from app.db.models import Event, SessionApp, WorkSession
from app.repositories.tenant import EventRepository, SessionRepository
from app.routers.common import NOT_FOUND, target_user, user_names

router = APIRouter(prefix="/sessions", tags=["sessions"])

Seconds = Annotated[int, Field(ge=0, le=7 * 24 * 3600)]
#: a session is still "running" while the app sent data within this time
LIVE_WINDOW = timedelta(minutes=2)


class AppIn(BaseModel):
    """Seconds in one application so far in this session (cumulative). Names only, no titles."""
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80,
                                           pattern=r"^[^\x00-\x1f\x7f]+$")]
    category: Literal["productive", "neutral", "distraction", "idle"]
    seconds: Seconds


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apps: Annotated[list[AppIn], Field(max_length=60)] = []
    id: uuid.UUID
    local_date: date
    started_at: datetime
    ended_at: datetime | None = None
    focus_seconds: Seconds = 0
    distraction_seconds: Seconds = 0
    away_seconds: Seconds = 0
    screen_productive_seconds: Seconds = 0
    screen_distracted_seconds: Seconds = 0
    screen_idle_seconds: Seconds = 0


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    session_id: uuid.UUID
    event_type: Literal["focus", "distraction", "away"]
    occurred_at: datetime
    app_name: Annotated[str, Field(max_length=120)] | None = None


class SyncBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessions: Annotated[list[SessionIn], Field(max_length=50)] = []
    events: Annotated[list[EventIn], Field(max_length=1000)] = []


class SyncResult(BaseModel):
    sessions: int
    events: int


class SessionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    local_date: date
    started_at: datetime
    ended_at: datetime | None
    running: bool
    focus_seconds: int
    distraction_seconds: int
    away_seconds: int
    screen_productive_seconds: int
    screen_distracted_seconds: int
    screen_idle_seconds: int


class EventOut(BaseModel):
    id: int
    session_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    app_name: str | None = None


COUNTERS = ("focus_seconds", "distraction_seconds", "away_seconds",
            "screen_productive_seconds", "screen_distracted_seconds", "screen_idle_seconds")


def is_running(row: WorkSession, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return row.ended_at is None and row.last_seen_at is not None and now - row.last_seen_at <= LIVE_WINDOW


def session_out(row: WorkSession, names) -> SessionOut:
    user = names.get(row.user_id)
    return SessionOut(id=row.id, user_id=row.user_id, full_name=user.full_name if user else "",
                      local_date=row.local_date, started_at=row.started_at, ended_at=row.ended_at,
                      running=is_running(row), **{c: getattr(row, c) for c in COUNTERS})


@router.post("/sync", response_model=SyncResult)
def sync(batch: SyncBatch, principal: CurrentUser):
    """Store the caller's own sessions and events. Rows of other users are ignored."""
    sessions = SessionRepository(principal.session, principal.company_id)
    now = datetime.now(UTC)
    stored_sessions = 0
    saved_ids: set[uuid.UUID] = set()      # sessions of this user that this batch stored
    for item in batch.sessions:
        row = sessions.get(item.id)
        if row is None:
            if principal.session.get(WorkSession, item.id) is not None:
                continue                      # the id exists elsewhere (should never happen)
            sessions.add(id=item.id, user_id=principal.user.id, local_date=item.local_date,
                         started_at=item.started_at, ended_at=item.ended_at, last_seen_at=now,
                         **{c: getattr(item, c) for c in COUNTERS})
        elif row.user_id == principal.user.id:
            values = {c: max(getattr(row, c), getattr(item, c)) for c in COUNTERS}
            if item.ended_at is not None and row.ended_at is None:
                values["ended_at"] = item.ended_at
            sessions.update(row, last_seen_at=now, **values)
        else:
            continue
        stored_sessions += 1
        saved_ids.add(item.id)

    merged: dict[tuple, dict] = {}         # one row per (session, app), even if the client repeats a name
    for item in batch.sessions:
        if item.id in saved_ids:
            for app in item.apps:
                row = merged.setdefault((item.id, app.name), {
                    "company_id": principal.company_id, "session_id": item.id, "user_id": principal.user.id,
                    "app_name": app.name, "category": app.category, "seconds": 0})
                row["seconds"] = max(row["seconds"], app.seconds)
    app_rows = list(merged.values())
    if app_rows:
        # cumulative counters only grow, so a late older sample never lowers them
        statement = insert(SessionApp).values(app_rows)
        principal.session.execute(statement.on_conflict_do_update(
            constraint="uq_session_apps_session_app",
            set_={"seconds": func.greatest(SessionApp.seconds, statement.excluded.seconds),
                  "category": statement.excluded.category}))

    own_sessions = {s.id for s in sessions.list(WorkSession.user_id == principal.user.id,
                                                 WorkSession.id.in_({e.session_id for e in batch.events}))} \
        if batch.events else set()
    rows = [{"company_id": principal.company_id, "client_event_id": e.id, "session_id": e.session_id,
             "user_id": principal.user.id, "event_type": e.event_type, "occurred_at": e.occurred_at,
             "app_name": e.app_name}
            for e in batch.events if e.session_id in own_sessions]
    stored_events = 0
    if rows:
        result = principal.session.execute(
            insert(Event).values(rows).on_conflict_do_nothing(constraint="uq_events_client_id")
            .returning(Event.id))
        stored_events = len(result.all())
    return SyncResult(sessions=stored_sessions, events=stored_events)


@router.get("", response_model=list[SessionOut])
def history(principal: CurrentUser, user_id: uuid.UUID | None = None,
            since: date | None = None, until: date | None = None,
            limit: int = Query(500, ge=1, le=2000), offset: int = Query(0, ge=0)):
    """Sessions newest first. Managers may ask for anyone (or everyone with no user_id);
    employees always get their own."""
    sessions = SessionRepository(principal.session, principal.company_id)
    conditions = []
    if principal.is_manager and user_id is None:
        pass
    else:
        conditions.append(WorkSession.user_id == target_user(principal, user_id).id)
    if since:
        conditions.append(WorkSession.local_date >= since)
    if until:
        conditions.append(WorkSession.local_date <= until)
    rows = sessions.list(*conditions, order_by=WorkSession.started_at.desc(), limit=limit, offset=offset)
    names = user_names(principal)
    return [session_out(row, names) for row in rows]


def _visible_session(principal, session_id: uuid.UUID) -> WorkSession:
    row = SessionRepository(principal.session, principal.company_id).get(session_id)
    if row is None or (not principal.is_manager and row.user_id != principal.user.id):
        raise NOT_FOUND
    return row


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: uuid.UUID, principal: CurrentUser):
    return session_out(_visible_session(principal, session_id), user_names(principal))


@router.get("/{session_id}/events", response_model=list[EventOut])
def session_events(session_id: uuid.UUID, principal: CurrentUser):
    _visible_session(principal, session_id)
    events = EventRepository(principal.session, principal.company_id)
    # events recorded in the same instant keep the order they were sent in
    return events.list(Event.session_id == session_id, order_by=(Event.occurred_at, Event.id))

