"""Database tables.

Every table except ``companies`` carries ``company_id``. References to users and
other rows use composite foreign keys ``(company_id, id)``, so a row can never point
at a user or record of another company even if application code made a mistake.
Row-Level Security policies (see the first migration) add a second, independent
guard on every table.
"""
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint,
    Index, Integer, String, Text, Time, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _company_id():
    return mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
                         nullable=False, index=True)


def _created():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


#: Names of every tenant table, in an order that is safe for TRUNCATE / reports.
TENANT_TABLES = (
    "users", "refresh_tokens", "invites", "sessions", "events", "tasks", "calendar_events",
    "calendar_attendees", "documents", "ai_usage", "meeting_requests", "messages",
    "notifications", "email_log", "ai_chats", "ai_messages", "session_apps",
)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    join_code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_id()
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: optional e-mails (meetings); urgent-task e-mails are always sent
    email_notifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    #: language of the e-mails this user receives
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="en", server_default="en")

    __table_args__ = (
        CheckConstraint("role IN ('manager', 'employee')", name="role_valid"),
        CheckConstraint("language IN ('en', 'ar')", name="language_valid"),
        CheckConstraint("status IN ('pending', 'active', 'disabled')", name="status_valid"),
        UniqueConstraint("company_id", "id", name="uq_users_company_id"),
        # one account per e-mail address across the whole service
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )


def _user_fk(column: str, name: str, ondelete: str = "CASCADE"):
    return ForeignKeyConstraint(["company_id", column], ["users.company_id", "users.id"],
                                name=name, ondelete=ondelete)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)   # the JWT's jti
    company_id: Mapped[uuid.UUID] = _company_id()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (_user_fk("user_id", "fk_refresh_tokens_user"),)


class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_id()
    email: Mapped[str | None] = mapped_column(String(254))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (_user_fk("created_by", "fk_invites_created_by"),)


class WorkSession(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_id()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    #: the employee's calendar date when the session started (their time zone, not UTC):
    #: "today" and "last 7 days" in reports are counted in local days, as before
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: last time the desktop app sent data for this session (a crashed app leaves the
    #: session open; reports treat it as running only while this is recent)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    focus_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    distraction_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    away_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    screen_productive_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    screen_distracted_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    screen_idle_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    __table_args__ = (
        _user_fk("user_id", "fk_sessions_user"),
        UniqueConstraint("company_id", "id", name="uq_sessions_company_id"),
        Index("ix_sessions_company_date", "company_id", "local_date"),
    )


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = _company_id()
    #: generated by the desktop app, so a batch that is sent twice is stored once
    client_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: active application name only (never a screenshot or window contents)
    app_name: Mapped[str | None] = mapped_column(String(120))
    __table_args__ = (
        CheckConstraint("event_type IN ('focus', 'distraction', 'away')", name="event_type_valid"),
        UniqueConstraint("company_id", "client_event_id", name="uq_events_client_id"),
        ForeignKeyConstraint(["company_id", "session_id"], ["sessions.company_id", "sessions.id"],
                             name="fk_events_session", ondelete="CASCADE"),
        _user_fk("user_id", "fk_events_user"),
    )


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_id()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal", server_default="normal")
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    deadline_date: Mapped[date | None] = mapped_column(Date)
    deadline_time: Mapped[time | None] = mapped_column(Time)
    created_at: Mapped[datetime] = _created()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("priority IN ('normal', 'urgent')", name="priority_valid"),
        _user_fk("user_id", "fk_tasks_user"),
        _user_fk("assigned_by", "fk_tasks_assigned_by", ondelete="SET NULL (assigned_by)"),
    )


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_id()
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    __table_args__ = (
        _user_fk("created_by", "fk_calendar_events_created_by"),
        UniqueConstraint("company_id", "id", name="uq_calendar_events_company_id"),
    )


class CalendarAttendee(Base):
    __tablename__ = "calendar_attendees"
    company_id: Mapped[uuid.UUID] = _company_id()
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "event_id"], ["calendar_events.company_id", "calendar_events.id"],
                             name="fk_calendar_attendees_event", ondelete="CASCADE"),
        _user_fk("user_id", "fk_calendar_attendees_user"),
    )


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_id()
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="everyone", server_default="everyone")
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    words: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("visibility IN ('everyone', 'managers')", name="visibility_valid"),
        Index("uq_documents_company_filename", "company_id", text("lower(filename)"), unique=True),
        _user_fk("uploaded_by", "fk_documents_uploaded_by", ondelete="SET NULL (uploaded_by)"),
    )


class AIUsage(Base):
    __tablename__ = "ai_usage"
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
                                                  primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class MeetingRequest(Base):
    __tablename__ = "meeting_requests"
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_id()
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000))
    #: 1-3 proposed times as ISO-8601 strings
    proposed_times: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    chosen_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decline_reason: Mapped[str | None] = mapped_column(String(1000))
    calendar_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    #: the manager's note when proposing other times
    reply_note: Mapped[str | None] = mapped_column(String(1000))
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'accepted', 'declined', 'rescheduled', 'cancelled')",
                        name="meeting_status_valid"),
        CheckConstraint("duration_minutes BETWEEN 15 AND 240", name="meeting_duration_valid"),
        _user_fk("requested_by", "fk_meeting_requests_requested_by"),
        _user_fk("manager_id", "fk_meeting_requests_manager", ondelete="SET NULL (manager_id)"),
        Index("ix_meeting_requests_company_status", "company_id", "status"),
        Index("ix_meeting_requests_requested_by", "company_id", "requested_by"),
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = _company_id()
    #: the conversation: one per employee with the company's managers
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("char_length(body) BETWEEN 1 AND 4000", name="message_length_valid"),
        _user_fk("employee_id", "fk_messages_employee"),
        _user_fk("sender_id", "fk_messages_sender"),
        Index("ix_messages_conversation", "company_id", "employee_id", "id"),
    )


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = _company_id()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(String(1000))
    link: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (_user_fk("user_id", "fk_notifications_user"),
                      Index("ix_notifications_user_unread", "company_id", "user_id", "read_at"))


class EmailLog(Base):
    """One row per e-mail. It is also the send queue: the background worker sends the
    ``queued`` rows that are due. The address and the body are never stored; ``payload``
    holds only what the template needs (title, time, who) until the e-mail is sent or
    given up, then it is emptied."""
    __tablename__ = "email_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = _company_id()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    template: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    #: urgent e-mails ignore the user's "optional e-mails" switch
    urgent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'sent', 'failed', 'skipped')", name="email_status_valid"),
        _user_fk("user_id", "fk_email_log_user", ondelete="SET NULL (user_id)"),
        Index("ix_email_log_due", "status", "next_attempt_at"),
    )


class AIChat(Base):
    """An AI Chat conversation; private to its owner."""
    __tablename__ = "ai_chats"
    id: Mapped[uuid.UUID] = _uuid_pk()
    company_id: Mapped[uuid.UUID] = _company_id()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    __table_args__ = (
        _user_fk("user_id", "fk_ai_chats_user"),
        UniqueConstraint("company_id", "id", name="uq_ai_chats_company_id"),
    )


class AIMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = _company_id()
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: who wrote an assistant message: 'engine' (from the database) or 'llm'
    source: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = _created()
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ai_message_role_valid"),
        CheckConstraint("char_length(content) <= 50000", name="ai_message_length_valid"),
        ForeignKeyConstraint(["company_id", "chat_id"], ["ai_chats.company_id", "ai_chats.id"],
                             name="fk_ai_messages_chat", ondelete="CASCADE"),
        Index("ix_ai_messages_chat", "company_id", "chat_id", "id"),
    )


class SessionApp(Base):
    """Seconds an employee spent in one application during one session.

    Only the application's display name (for example "Chrome") and its category are
    stored -- never window titles, page titles or file names. Seconds only grow.
    """
    __tablename__ = "session_apps"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = _company_id()
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    app_name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    __table_args__ = (
        CheckConstraint("category IN ('productive', 'neutral', 'distraction', 'idle')", name="app_category_valid"),
        CheckConstraint("seconds >= 0", name="app_seconds_valid"),
        UniqueConstraint("company_id", "session_id", "app_name", name="uq_session_apps_session_app"),
        ForeignKeyConstraint(["company_id", "session_id"], ["sessions.company_id", "sessions.id"],
                             name="fk_session_apps_session", ondelete="CASCADE"),
        _user_fk("user_id", "fk_session_apps_user"),
        Index("ix_session_apps_company_user", "company_id", "user_id"),
    )
