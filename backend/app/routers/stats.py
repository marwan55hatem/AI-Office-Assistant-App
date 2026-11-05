"""/stats and /events/recent: the numbers behind the manager dashboard and the chat.

Days are the employees' local calendar days (``sessions.local_date``); the app passes
its own "today" so the server never guesses a time zone.
"""
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.deps import CurrentManager, CurrentUser
from app.db.models import Event, User, WorkSession
from app.routers.common import target_user
from app.routers.sessions import LIVE_WINDOW

router = APIRouter(tags=["stats"])


class EmployeeToday(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    status: str
    focus_seconds: int
    distraction_seconds: int
    away_seconds: int
    sessions: int
    running: bool
    last_event_type: str | None


class Totals(BaseModel):
    focus_seconds: int
    distraction_seconds: int
    away_seconds: int


class TodayOut(BaseModel):
    day: date
    totals: Totals
    running_sessions: int
    employees: list[EmployeeToday]


class RangeRow(BaseModel):
    id: uuid.UUID
    full_name: str
    total_focus: int
    total_distraction: int
    total_away: int
    total_sessions: int


class RecentEvent(BaseModel):
    id: int
    session_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    full_name: str


def _sums(*conditions):
    return (select(WorkSession.user_id,
                   func.coalesce(func.sum(WorkSession.focus_seconds), 0).label("focus"),
                   func.coalesce(func.sum(WorkSession.distraction_seconds), 0).label("distraction"),
                   func.coalesce(func.sum(WorkSession.away_seconds), 0).label("away"),
                   func.count().label("sessions"))
            .where(*conditions).group_by(WorkSession.user_id))


@router.get("/stats/today", response_model=TodayOut)
def today(principal: CurrentManager, day: date = Query(...)):
    s = principal.session
    cid = principal.company_id
    live_since = datetime.now(UTC) - LIVE_WINDOW
    sums = {row.user_id: row for row in s.execute(_sums(WorkSession.company_id == cid, WorkSession.local_date == day))}
    running = s.execute(
        select(WorkSession.user_id, WorkSession.id)
        .where(WorkSession.company_id == cid, WorkSession.local_date == day,
               WorkSession.ended_at.is_(None), WorkSession.last_seen_at >= live_since)).all()
    running_by_user = {}
    for user_id, session_id in running:
        running_by_user.setdefault(user_id, session_id)
    last_event = {}
    if running_by_user:
        ranked = (select(Event.session_id, Event.event_type,
                         func.row_number().over(partition_by=Event.session_id,
                                                order_by=Event.occurred_at.desc()).label("n"))
                  .where(Event.company_id == cid, Event.session_id.in_(list(running_by_user.values())))
                  .subquery())
        last_event = {r.session_id: r.event_type for r in s.execute(select(ranked).where(ranked.c.n == 1))}
    employees = s.scalars(select(User).where(User.company_id == cid, User.role == "employee")
                          .order_by(User.full_name)).all()
    rows = []
    for user in employees:
        summary = sums.get(user.id)
        open_session = running_by_user.get(user.id)
        rows.append(EmployeeToday(
            id=user.id, full_name=user.full_name, email=user.email, status=user.status,
            focus_seconds=summary.focus if summary else 0,
            distraction_seconds=summary.distraction if summary else 0,
            away_seconds=summary.away if summary else 0,
            sessions=summary.sessions if summary else 0,
            running=open_session is not None,
            last_event_type=last_event.get(open_session) if open_session else None))
    totals = Totals(focus_seconds=sum(r.focus for r in sums.values()),
                    distraction_seconds=sum(r.distraction for r in sums.values()),
                    away_seconds=sum(r.away for r in sums.values()))
    return TodayOut(day=day, totals=totals, running_sessions=len(running), employees=rows)


@router.get("/stats/range", response_model=list[RangeRow])
def date_range(principal: CurrentUser, start: date = Query(...), end: date = Query(...),
               user_id: uuid.UUID | None = None):
    """Totals per employee between two local dates (inclusive). Managers get every
    employee (or one); employees only themselves."""
    s = principal.session
    cid = principal.company_id
    if principal.is_manager and user_id is None:
        users = s.scalars(select(User).where(User.company_id == cid, User.role == "employee")
                          .order_by(User.full_name)).all()
    else:
        users = [target_user(principal, user_id)]
    sums = {row.user_id: row for row in s.execute(_sums(
        WorkSession.company_id == cid, WorkSession.local_date >= start, WorkSession.local_date <= end,
        WorkSession.user_id.in_([u.id for u in users])))}
    return [RangeRow(id=u.id, full_name=u.full_name,
                     total_focus=sums[u.id].focus if u.id in sums else 0,
                     total_distraction=sums[u.id].distraction if u.id in sums else 0,
                     total_away=sums[u.id].away if u.id in sums else 0,
                     total_sessions=sums[u.id].sessions if u.id in sums else 0) for u in users]


@router.get("/events/recent", response_model=list[RecentEvent])
def recent_events(principal: CurrentManager, limit: int = Query(10, ge=1, le=200)):
    rows = principal.session.execute(
        select(Event.id, Event.session_id, Event.event_type, Event.occurred_at, User.full_name)
        .join(User, (User.company_id == Event.company_id) & (User.id == Event.user_id))
        .where(Event.company_id == principal.company_id)
        .order_by(Event.occurred_at.desc(), Event.id.desc()).limit(limit)).all()
    return [RecentEvent(**row._mapping) for row in rows]

