"""/notifications: your own in-app notifications (nobody can read anyone else's)."""
from datetime import UTC, datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update

from app.core.deps import CurrentUser
from app.db.models import Notification
from app.repositories.tenant import NotificationRepository
from app.routers.common import NOT_FOUND

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    title: str
    body: str | None
    link: str | None
    created_at: datetime
    read_at: datetime | None


def _mine(principal):
    return Notification.user_id == principal.user.id


@router.get("", response_model=list[NotificationOut])
def list_notifications(principal: CurrentUser, unread: bool = False, limit: int = Query(50, ge=1, le=200),
                       offset: int = Query(0, ge=0)):
    conditions = [_mine(principal)]
    if unread:
        conditions.append(Notification.read_at.is_(None))
    return NotificationRepository(principal.session, principal.company_id).list(
        *conditions, order_by=Notification.id.desc(), limit=limit, offset=offset)


@router.get("/unread-count")
def unread_count(principal: CurrentUser) -> dict:
    count = principal.session.scalar(select(func.count()).select_from(Notification).where(
        Notification.company_id == principal.company_id, _mine(principal), Notification.read_at.is_(None)))
    return {"unread": count or 0}


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, principal: CurrentUser):
    notifications = NotificationRepository(principal.session, principal.company_id)
    row = notifications.get(notification_id)
    if row is None or row.user_id != principal.user.id:
        raise NOT_FOUND
    if row.read_at is None:
        notifications.update(row, read_at=datetime.now(UTC))
    return row


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(principal: CurrentUser):
    principal.session.execute(update(Notification).where(
        Notification.company_id == principal.company_id, _mine(principal), Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC)))
