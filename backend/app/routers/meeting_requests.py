"""/meeting-requests: an employee asks the manager for a meeting.

Lifecycle (who may do what)::

    employee asks ............................ pending   (1-3 proposed times)
    manager accepts one proposed time ........ accepted  (a calendar event for both)
    manager declines, with a reason .......... declined
    manager proposes other times ............. rescheduled
        employee accepts one of them ......... accepted
        manager may decline or propose again
    employee cancels (pending / rescheduled / accepted) ... cancelled
    manager cancels an accepted meeting ...... cancelled (the calendar event is removed)

declined and cancelled are final. Each step notifies the other side in the app and by
e-mail (an optional e-mail: the user's "meeting e-mails" switch applies). A request row
is locked while it changes, so two managers cannot both answer it.

Times are ISO-8601 date-times with the person's UTC offset. The calendar event uses the
wall-clock time in that offset, the way the person entered it.
"""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import func, select

from app.core.deps import CurrentUser
from app.db.models import CalendarAttendee, CalendarEvent, MeetingRequest, User
from app.repositories.tenant import CalendarEventRepository, MeetingRequestRepository, UserRepository
from app.routers.common import MANAGERS_ONLY, NOT_FOUND
from app.services.notify import notify

router = APIRouter(prefix="/meeting-requests", tags=["meeting requests"])

Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Times = Annotated[list[AwareDatetime], Field(min_length=1, max_length=3)]
Duration = Annotated[int, Field(ge=15, le=240)]
MAX_DAYS_AHEAD = 366


def _check_times(times: list[datetime]) -> list[datetime]:
    now = datetime.now(UTC)
    if len({t.astimezone(UTC) for t in times}) != len(times):
        raise ValueError("the proposed times must be different")
    for moment in times:
        if moment <= now:
            raise ValueError("proposed times must be in the future")
        if moment > now + timedelta(days=MAX_DAYS_AHEAD):
            raise ValueError("proposed times must be within a year")
    return sorted(times, key=lambda t: t.astimezone(UTC))


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Topic
    note: Note | None = None
    proposed_times: Times
    duration_minutes: Duration = 30
    #: a particular manager; empty = any manager of the company
    manager_id: uuid.UUID | None = None

    @field_validator("proposed_times")
    @classmethod
    def _times(cls, value):
        return _check_times(value)


class AcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time: AwareDatetime
    duration_minutes: Duration | None = None


class DeclineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason


class RescheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposed_times: Times
    note: Note | None = None

    @field_validator("proposed_times")
    @classmethod
    def _times(cls, value):
        return _check_times(value)


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Note | None = None


class RequestOut(BaseModel):
    id: uuid.UUID
    topic: str
    note: str | None
    proposed_times: list[str]
    duration_minutes: int
    status: str
    chosen_time: str | None
    decline_reason: str | None
    reply_note: str | None
    calendar_event_id: uuid.UUID | None
    requested_by: uuid.UUID
    requested_by_name: str
    manager_id: uuid.UUID | None
    manager_name: str | None
    created_at: datetime
    updated_at: datetime
    #: whose move it is: "manager", "employee" or None (final)
    waiting_for: str | None


def _waiting_for(row: MeetingRequest) -> str | None:
    return {"pending": "manager", "rescheduled": "employee"}.get(row.status)


def _out(principal, row: MeetingRequest, names: dict | None = None) -> RequestOut:
    names = names if names is not None else {}
    users = UserRepository(principal.session, principal.company_id)

    def name(user_id):
        if user_id is None:
            return None
        if user_id not in names:
            user = users.get(user_id)
            names[user_id] = user.full_name if user else ""
        return names[user_id]

    return RequestOut(id=row.id, topic=row.topic, note=row.note, proposed_times=list(row.proposed_times),
                      duration_minutes=row.duration_minutes, status=row.status,
                      chosen_time=row.chosen_time.isoformat() if row.chosen_time else None,
                      decline_reason=row.decline_reason, reply_note=row.reply_note,
                      calendar_event_id=row.calendar_event_id, requested_by=row.requested_by,
                      requested_by_name=name(row.requested_by) or "", manager_id=row.manager_id,
                      manager_name=name(row.manager_id), created_at=row.created_at, updated_at=row.updated_at,
                      waiting_for=_waiting_for(row))


def _visible(principal):
    query = MeetingRequestRepository(principal.session, principal.company_id).query()
    if not principal.is_manager:
        query = query.where(MeetingRequest.requested_by == principal.user.id)
    return query


def _locked(principal, request_id) -> MeetingRequest:
    """The request, locked for this transaction (someone else answering waits, then sees the new state)."""
    row = principal.session.scalars(_visible(principal).where(MeetingRequest.id == request_id)
                                    .with_for_update()).first()
    if row is None:
        raise NOT_FOUND
    return row


def _conflict(row: MeetingRequest):
    return HTTPException(status.HTTP_409_CONFLICT, f"This request is {row.status} and cannot be changed that way")


def _managers(principal, row: MeetingRequest) -> list[User]:
    """Who hears about the employee's side: the request's manager, or every active manager."""
    users = UserRepository(principal.session, principal.company_id)
    if row.manager_id is not None:
        manager = users.get(row.manager_id)
        if manager is not None and manager.status == "active":
            return [manager]
    return users.list(User.role == "manager", User.status == "active")


def _employee(principal, row: MeetingRequest) -> User | None:
    return UserRepository(principal.session, principal.company_id).get(row.requested_by)


def _tell(principal, people, row: MeetingRequest, template: str, title: str, body: str | None = None, **extra):
    payload = {"title": row.topic, "who": principal.user.full_name, **extra}
    for person in people:
        if person is not None and person.id != principal.user.id:
            notify(principal.session, principal.company_id, person, template, title, body,
                   link=f"meeting-request:{row.id}", email_template=template, payload=dict(payload))


def _touch(row: MeetingRequest, **values) -> None:
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)


def _times_text(times) -> str:
    return ", ".join(datetime.fromisoformat(t).strftime("%a %d %b %H:%M") for t in times)


# ---------------------------------------------------------------- reading
@router.get("", response_model=list[RequestOut])
def list_requests(principal: CurrentUser,
                  status_filter: Literal["pending", "accepted", "declined", "rescheduled", "cancelled", "open"] | None
                  = Query(None, alias="status"),
                  limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    """Employees see their own requests, managers the company's. ``status=open`` = pending or rescheduled."""
    query = _visible(principal)
    if status_filter == "open":
        query = query.where(MeetingRequest.status.in_(("pending", "rescheduled")))
    elif status_filter:
        query = query.where(MeetingRequest.status == status_filter)
    rows = principal.session.scalars(query.order_by(MeetingRequest.updated_at.desc()).limit(limit).offset(offset))
    names = {}
    return [_out(principal, row, names) for row in rows]


@router.get("/waiting-count")
def waiting_count(principal: CurrentUser) -> dict:
    """How many requests wait for *you*: pending ones for a manager, rescheduled ones for an employee."""
    waiting = "pending" if principal.is_manager else "rescheduled"
    query = _visible(principal).where(MeetingRequest.status == waiting)
    count = principal.session.scalar(select(func.count()).select_from(query.subquery()))
    return {"waiting": count or 0}


@router.get("/{request_id}", response_model=RequestOut)
def get_request(request_id: uuid.UUID, principal: CurrentUser):
    row = principal.session.scalars(_visible(principal).where(MeetingRequest.id == request_id)).first()
    if row is None:
        raise NOT_FOUND
    return _out(principal, row)


# ---------------------------------------------------------------- the lifecycle
@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
def create_request(body: RequestIn, principal: CurrentUser):
    if principal.is_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Managers add meetings directly in the calendar")
    if body.manager_id is not None:
        manager = UserRepository(principal.session, principal.company_id).get(body.manager_id)
        if manager is None or manager.role != "manager" or manager.status != "active":
            raise NOT_FOUND
    row = MeetingRequestRepository(principal.session, principal.company_id).add(
        requested_by=principal.user.id, manager_id=body.manager_id, topic=body.topic, note=body.note or None,
        proposed_times=[t.isoformat() for t in body.proposed_times], duration_minutes=body.duration_minutes,
        status="pending")
    _tell(principal, _managers(principal, row), row, "meeting_request_new",
          f"Meeting request from {principal.user.full_name}", f"{row.topic} — {_times_text(row.proposed_times)}",
          times=list(row.proposed_times), note=row.note)
    return _out(principal, row)


def _add_to_calendar(principal, row: MeetingRequest, moment: datetime, organiser_id: uuid.UUID) -> CalendarEvent:
    end = moment + timedelta(minutes=row.duration_minutes)
    event = CalendarEventRepository(principal.session, principal.company_id).add(
        title=f"Meeting: {row.topic}"[:200], description=row.note, event_date=moment.date(),
        start_time=moment.time().replace(tzinfo=None),
        end_time=end.time().replace(tzinfo=None) if end.date() == moment.date() else None,
        created_by=organiser_id)
    principal.session.add(CalendarAttendee(company_id=principal.company_id, event_id=event.id,
                                           user_id=row.requested_by))
    principal.session.flush()
    return event


@router.post("/{request_id}/accept", response_model=RequestOut)
def accept(request_id: uuid.UUID, body: AcceptIn, principal: CurrentUser):
    """Pick one of the proposed times: the manager on a pending request, the employee on a
    rescheduled one (the manager's proposal). It goes into both calendars."""
    row = _locked(principal, request_id)
    if row.status != ("pending" if principal.is_manager else "rescheduled"):
        raise _conflict(row)
    proposed = {datetime.fromisoformat(t).astimezone(UTC): t for t in row.proposed_times}
    chosen = proposed.get(body.time.astimezone(UTC))
    if chosen is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick one of the proposed times")
    moment = datetime.fromisoformat(chosen)                # keeps the offset the time was proposed in
    if moment <= datetime.now(UTC):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That time has already passed")
    organiser = principal.user.id if principal.is_manager else row.manager_id
    if organiser is None:
        raise _conflict(row)
    if body.duration_minutes:
        row.duration_minutes = body.duration_minutes
    event = _add_to_calendar(principal, row, moment, organiser)
    _touch(row, status="accepted", chosen_time=moment, calendar_event_id=event.id, manager_id=organiser)
    other = [_employee(principal, row)] if principal.is_manager else _managers(principal, row)
    _tell(principal, other, row, "meeting_request_accepted", f"Meeting accepted: {row.topic}",
          f"{moment.strftime('%a %d %b %H:%M')} ({row.duration_minutes} min) — in your calendar", when=chosen)
    principal.session.flush()
    return _out(principal, row)


@router.post("/{request_id}/decline", response_model=RequestOut)
def decline(request_id: uuid.UUID, body: DeclineIn, principal: CurrentUser):
    if not principal.is_manager:
        raise MANAGERS_ONLY
    row = _locked(principal, request_id)
    if row.status not in ("pending", "rescheduled"):
        raise _conflict(row)
    _touch(row, status="declined", decline_reason=body.reason, manager_id=principal.user.id)
    _tell(principal, [_employee(principal, row)], row, "meeting_request_declined",
          f"Meeting request declined: {row.topic}", body.reason, reason=body.reason)
    principal.session.flush()
    return _out(principal, row)


@router.post("/{request_id}/reschedule", response_model=RequestOut)
def reschedule(request_id: uuid.UUID, body: RescheduleIn, principal: CurrentUser):
    """The manager proposes other times; the employee then picks one (or cancels)."""
    if not principal.is_manager:
        raise MANAGERS_ONLY
    row = _locked(principal, request_id)
    if row.status not in ("pending", "rescheduled"):
        raise _conflict(row)
    times = [t.isoformat() for t in body.proposed_times]
    _touch(row, status="rescheduled", proposed_times=times, reply_note=body.note or None,
           manager_id=principal.user.id)
    _tell(principal, [_employee(principal, row)], row, "meeting_request_rescheduled",
          f"Other times proposed: {row.topic}", _times_text(times), times=times, note=row.reply_note)
    principal.session.flush()
    return _out(principal, row)


@router.post("/{request_id}/cancel", response_model=RequestOut)
def cancel(request_id: uuid.UUID, principal: CurrentUser, body: CancelIn | None = None):
    """The employee may cancel their open or accepted request; a manager an accepted meeting
    (an open request is declined instead). An accepted meeting leaves both calendars."""
    row = _locked(principal, request_id)
    allowed = ("accepted",) if principal.is_manager else ("pending", "rescheduled", "accepted")
    if row.status not in allowed:
        raise _conflict(row)
    if row.calendar_event_id is not None:
        events = CalendarEventRepository(principal.session, principal.company_id)
        event = events.get(row.calendar_event_id)
        if event is not None:
            events.delete(event)
    reason = body.reason if body and body.reason else None
    _touch(row, status="cancelled", calendar_event_id=None, decline_reason=reason)
    other = [_employee(principal, row)] if principal.is_manager else _managers(principal, row)
    _tell(principal, other, row, "meeting_request_cancelled", f"Meeting request cancelled: {row.topic}", reason,
          reason=reason)
    principal.session.flush()
    return _out(principal, row)
