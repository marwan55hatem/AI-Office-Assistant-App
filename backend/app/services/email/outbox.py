"""Putting e-mails in the queue (the ``email_log`` table).

The row is written in the same transaction as the change that caused it (the task or
the meeting), so an e-mail is queued exactly when the change is saved, and never for a
change that was rolled back. The background worker sends it afterwards.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.db.models import CalendarEvent, EmailLog, Task, User
from app.repositories.tenant import UserRepository

OPTED_OUT = "turned off by the user"


def queue_email(session: Session, company_id: uuid.UUID, user: User, template: str, payload: dict,
                urgent: bool = False) -> EmailLog:
    """Queue one e-mail to ``user``. Optional e-mails to someone who turned them off are
    recorded as 'skipped' (every e-mail decision is in the log)."""
    skipped = not urgent and not user.email_notifications
    row = EmailLog(company_id=company_id, user_id=user.id, template=template, urgent=urgent,
                   status="skipped" if skipped else "queued", error=OPTED_OUT if skipped else None,
                   payload={} if skipped else payload)
    session.add(row)
    session.flush()
    return row


def task_payload(task: Task, who: str) -> dict:
    return {"title": task.title, "who": who,
            "date": task.deadline_date.isoformat() if task.deadline_date else None,
            "time": task.deadline_time.isoformat() if task.deadline_time else None}


def meeting_payload(event: CalendarEvent, who: str) -> dict:
    return {"title": event.title, "who": who, "date": event.event_date.isoformat(),
            "start": event.start_time.isoformat() if event.start_time else None,
            "end": event.end_time.isoformat() if event.end_time else None}


def queue_urgent_task(session: Session, company_id: uuid.UUID, task: Task, assigned_by: User) -> EmailLog | None:
    """A manager gave someone an urgent task: always e-mailed."""
    if task.priority != "urgent" or task.assigned_by is None or task.user_id == assigned_by.id:
        return None
    owner = UserRepository(session, company_id).get(task.user_id)
    if owner is None or owner.status != "active":
        return None
    return queue_email(session, company_id, owner, "task_urgent", task_payload(task, assigned_by.full_name),
                       urgent=True)


def queue_meeting(session: Session, company_id: uuid.UUID, event: CalendarEvent, template: str,
                  user_ids: Iterable[uuid.UUID], actor: User) -> list[EmailLog]:
    """Meeting invites, changes and cancellations (optional e-mails). The person who made
    the change is never e-mailed about it."""
    users = UserRepository(session, company_id)
    payload = meeting_payload(event, actor.full_name)
    rows = []
    for user_id in sorted(set(user_ids) - {actor.id}):
        user = users.get(user_id)
        if user is not None and user.status == "active":
            rows.append(queue_email(session, company_id, user, template, dict(payload)))
    return rows
