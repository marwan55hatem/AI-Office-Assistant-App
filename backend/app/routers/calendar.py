"""/calendar: events created by managers, with invited employees.

Everyone sees the events they created or are invited to (as before: a manager does not
see another manager's events unless invited). Only managers create, change and delete
events and choose attendees.

Attendees are e-mailed (optional e-mails, see Phase 5) when they are invited, when the
title or time of the meeting changes, and when it is cancelled or they are removed.
"""
import uuid
from datetime import UTC, date, datetime, time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import delete, func, or_, select

from app.core.deps import CurrentManager, CurrentUser
from app.db.models import CalendarAttendee, CalendarEvent, User
from app.repositories.tenant import CalendarEventRepository, UserRepository
from app.routers.common import NOT_FOUND
from app.services.email.outbox import queue_meeting

#: changes that attendees are told about (a new description alone is not e-mailed)
NOTIFY_FIELDS = ("title", "event_date", "start_time", "end_time")

router = APIRouter(prefix="/calendar", tags=["calendar"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_UNSET = object()


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    event_date: date
    description: Annotated[str, Field(max_length=5000)] | None = None
    start_time: time | None = None
    end_time: time | None = None


class EventPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title | None = None
    event_date: date | None = None
    description: Annotated[str, Field(max_length=5000)] | None = None
    start_time: time | None = None
    end_time: time | None = None


class AttendeesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_ids: Annotated[list[uuid.UUID], Field(max_length=1000)]


class Attendee(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str


class EventOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    event_date: date
    start_time: time | None
    end_time: time | None
    created_by: uuid.UUID
    created_by_name: str
    created_at: datetime
    attendee_count: int
    attendees: list[Attendee] | None = None


def _attendees(principal, event_id) -> list[Attendee]:
    rows = principal.session.execute(
        select(User.id, User.email, User.full_name)
        .join(CalendarAttendee, (CalendarAttendee.company_id == User.company_id) & (CalendarAttendee.user_id == User.id))
        .where(CalendarAttendee.company_id == principal.company_id, CalendarAttendee.event_id == event_id)
        .order_by(User.full_name)).all()
    return [Attendee(id=r.id, email=r.email, full_name=r.full_name) for r in rows]


def _out(principal, event: CalendarEvent, names, counts, with_attendees=False) -> EventOut:
    creator = names.get(event.created_by)
    return EventOut(id=event.id, title=event.title, description=event.description, event_date=event.event_date,
                    start_time=event.start_time, end_time=event.end_time, created_by=event.created_by,
                    created_by_name=creator.full_name if creator else "", created_at=event.created_at,
                    attendee_count=counts.get(event.id, 0),
                    attendees=_attendees(principal, event.id) if with_attendees else None)


def _counts(principal, event_ids) -> dict:
    if not event_ids:
        return {}
    rows = principal.session.execute(
        select(CalendarAttendee.event_id, func.count())
        .where(CalendarAttendee.company_id == principal.company_id, CalendarAttendee.event_id.in_(event_ids))
        .group_by(CalendarAttendee.event_id)).all()
    return dict(rows)


def _names(principal):
    return {u.id: u for u in UserRepository(principal.session, principal.company_id).list()}


def _attendee_ids(principal, event_id) -> set:
    return set(principal.session.scalars(select(CalendarAttendee.user_id).where(
        CalendarAttendee.company_id == principal.company_id, CalendarAttendee.event_id == event_id)))


def _visible_query(principal):
    invited = select(CalendarAttendee.event_id).where(CalendarAttendee.company_id == principal.company_id,
                                                      CalendarAttendee.user_id == principal.user.id)
    return CalendarEventRepository(principal.session, principal.company_id).query().where(
        or_(CalendarEvent.created_by == principal.user.id, CalendarEvent.id.in_(invited)))


@router.get("", response_model=list[EventOut])
def list_events(principal: CurrentUser, start: date | None = None, end: date | None = None,
                limit: int = Query(1000, ge=1, le=5000)):
    statement = _visible_query(principal)
    if start:
        statement = statement.where(CalendarEvent.event_date >= start)
    if end:
        statement = statement.where(CalendarEvent.event_date <= end)
    statement = statement.order_by(CalendarEvent.event_date, CalendarEvent.start_time.is_not(None),
                                   CalendarEvent.start_time, CalendarEvent.created_at).limit(limit)
    events = list(principal.session.scalars(statement))
    names, counts = _names(principal), _counts(principal, [e.id for e in events])
    return [_out(principal, e, names, counts) for e in events]


def _visible(principal, event_id) -> CalendarEvent:
    event = principal.session.scalars(_visible_query(principal).where(CalendarEvent.id == event_id)).first()
    if event is None and principal.is_manager:
        event = CalendarEventRepository(principal.session, principal.company_id).get(event_id)
    if event is None:
        raise NOT_FOUND
    return event


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: uuid.UUID, principal: CurrentUser):
    event = _visible(principal, event_id)
    return _out(principal, event, _names(principal), _counts(principal, [event.id]), with_attendees=True)


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(body: EventIn, principal: CurrentManager):
    event = CalendarEventRepository(principal.session, principal.company_id).add(
        created_by=principal.user.id, **body.model_dump())
    return _out(principal, event, _names(principal), {})


@router.patch("/{event_id}", response_model=EventOut)
def update_event(event_id: uuid.UUID, body: EventPatch, principal: CurrentManager):
    events = CalendarEventRepository(principal.session, principal.company_id)
    event = events.get(event_id)
    if event is None:
        raise NOT_FOUND
    changes = body.model_dump(exclude_unset=True)
    for required in ("title", "event_date"):
        if required in changes and changes[required] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{required} cannot be empty")
    changed = any(field in changes and changes[field] != getattr(event, field) for field in NOTIFY_FIELDS)
    events.update(event, updated_at=datetime.now(UTC), **changes)
    if changed:
        queue_meeting(principal.session, principal.company_id, event, "meeting_changed",
                      _attendee_ids(principal, event.id), principal.user)
    return _out(principal, event, _names(principal), _counts(principal, [event.id]))


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: uuid.UUID, principal: CurrentManager):
    events = CalendarEventRepository(principal.session, principal.company_id)
    event = events.get(event_id)
    if event is None:
        raise NOT_FOUND
    queue_meeting(principal.session, principal.company_id, event, "meeting_cancelled",
                  _attendee_ids(principal, event.id), principal.user)
    events.delete(event)


@router.put("/{event_id}/attendees", response_model=list[Attendee])
def set_attendees(event_id: uuid.UUID, body: AttendeesIn, principal: CurrentManager):
    """Replace the attendee list (a snapshot: people added later are not invited)."""
    event = CalendarEventRepository(principal.session, principal.company_id).get(event_id)
    if event is None:
        raise NOT_FOUND
    users = UserRepository(principal.session, principal.company_id)
    wanted = {uid for uid in body.user_ids if users.get(uid) is not None}
    before = _attendee_ids(principal, event_id)
    queue_meeting(principal.session, principal.company_id, event, "meeting_invite", wanted - before, principal.user)
    queue_meeting(principal.session, principal.company_id, event, "meeting_cancelled", before - wanted,
                  principal.user)
    principal.session.execute(delete(CalendarAttendee).where(
        CalendarAttendee.company_id == principal.company_id, CalendarAttendee.event_id == event_id))
    for user_id in sorted(wanted):
        principal.session.add(CalendarAttendee(company_id=principal.company_id, event_id=event_id, user_id=user_id))
    principal.session.flush()
    return _attendees(principal, event_id)
