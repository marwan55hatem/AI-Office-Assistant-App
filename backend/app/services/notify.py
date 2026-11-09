"""In-app notifications, optionally with an e-mail.

The notification row and the queued e-mail are written in the caller's transaction, so
they exist exactly when the change that caused them is saved.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models import Notification, User
from app.repositories.tenant import NotificationRepository
from app.services.email.outbox import queue_email


def notify(session: Session, company_id: uuid.UUID, user: User, kind: str, title: str, body: str | None = None,
           link: str | None = None, email_template: str | None = None, payload: dict | None = None) -> Notification:
    row = NotificationRepository(session, company_id).add(user_id=user.id, kind=kind, title=title[:200],
                                                          body=body[:1000] if body else None, link=link)
    if email_template and user.status == "active":
        queue_email(session, company_id, user, email_template, payload or {})
    return row
