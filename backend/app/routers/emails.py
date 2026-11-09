"""/email-log: the record of every e-mail the company's people were sent (managers only).

Rows hold the template, the status and the error kind -- never an address or a body.
"""
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from app.core.deps import CurrentManager
from app.db.models import EmailLog
from app.repositories.tenant import EmailLogRepository

router = APIRouter(prefix="/email-log", tags=["email"])


class EmailLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: uuid.UUID | None
    template: str
    status: str
    urgent: bool
    attempts: int
    error: str | None
    created_at: datetime
    sent_at: datetime | None
    next_attempt_at: datetime | None


@router.get("", response_model=list[EmailLogOut])
def email_log(principal: CurrentManager, status: Literal["queued", "sent", "failed", "skipped"] | None = None,
              user_id: uuid.UUID | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    conditions = []
    if status:
        conditions.append(EmailLog.status == status)
    if user_id:
        conditions.append(EmailLog.user_id == user_id)
    return EmailLogRepository(principal.session, principal.company_id).list(
        *conditions, order_by=EmailLog.id.desc(), limit=limit, offset=offset)
