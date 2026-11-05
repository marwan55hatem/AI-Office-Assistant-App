"""Concrete repositories, one per table. All inherit the company filter from the base."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, text, update
from sqlalchemy.orm import Session

from app.db import models
from app.repositories.base import TenantRepository


class UserRepository(TenantRepository[models.User]):
    model = models.User

    def by_email(self, email: str) -> models.User | None:
        return self.session.scalars(self.query().where(func.lower(models.User.email) == email.lower())).first()


class RefreshTokenRepository(TenantRepository[models.RefreshToken]):
    model = models.RefreshToken

    def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        self.session.execute(
            update(models.RefreshToken)
            .where(models.RefreshToken.company_id == self.company_id,
                   models.RefreshToken.user_id == user_id,
                   models.RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC)))


class InviteRepository(TenantRepository[models.Invite]):
    model = models.Invite


class SessionRepository(TenantRepository[models.WorkSession]):
    model = models.WorkSession


class EventRepository(TenantRepository[models.Event]):
    model = models.Event


class TaskRepository(TenantRepository[models.Task]):
    model = models.Task


class CalendarEventRepository(TenantRepository[models.CalendarEvent]):
    model = models.CalendarEvent


class DocumentRepository(TenantRepository[models.Document]):
    model = models.Document


class MeetingRequestRepository(TenantRepository[models.MeetingRequest]):
    model = models.MeetingRequest


class MessageRepository(TenantRepository[models.Message]):
    model = models.Message


class NotificationRepository(TenantRepository[models.Notification]):
    model = models.Notification


class EmailLogRepository(TenantRepository[models.EmailLog]):
    model = models.EmailLog


class CompanyRepository:
    """The company row itself (not a tenant table: it *is* the tenant)."""

    def __init__(self, session: Session, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    def get(self) -> models.Company | None:
        return self.session.get(models.Company, self.company_id)


# -- lookups that must work before the company is known (login, join) ----------
# They call SECURITY DEFINER functions created by the migration, which return only
# the few columns needed; the app role has no other way to read across companies.

def find_login(session: Session, email: str):
    return session.execute(text("SELECT * FROM auth_find_user(:email)"), {"email": email}).first()


def find_company_by_code(session: Session, code: str) -> uuid.UUID | None:
    return session.execute(text("SELECT auth_company_by_code(:code)"), {"code": code}).scalar()


def find_invite(session: Session, token_hash: str):
    return session.execute(text("SELECT * FROM auth_find_invite(:h)"), {"h": token_hash}).first()


def email_taken(session: Session, email: str) -> bool:
    return bool(session.execute(text("SELECT auth_email_taken(:email)"), {"email": email}).scalar())
