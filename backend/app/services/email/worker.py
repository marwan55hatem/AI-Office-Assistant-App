"""The background sender: sends queued e-mails, retries the ones that fail.

* It asks the database which companies have e-mail due (``email_due_companies``, the only
  cross-company step, returning company ids only), then works inside each company's own
  tenant context, one e-mail per transaction, locking the row (``FOR UPDATE SKIP LOCKED``)
  so two workers never send the same e-mail.
* A failure that may pass (network, rate limit, provider down) is retried after 1 min,
  5 min, 30 min, 2 h ... up to ``EMAIL_MAX_ATTEMPTS``; a permanent one (refused address,
  bad key) is marked failed at once.
* The recipient's address is read from their user row at send time, and the preference is
  checked again, so turning optional e-mails off also stops ones already queued.
* Sending is "at least once": if the process stops between the provider accepting an
  e-mail and the commit, it is sent again; Resend drops the repeat (idempotency key).
"""
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, text

from app.core.config import get_settings
from app.db.models import EmailLog
from app.db.session import transaction
from app.repositories.tenant import UserRepository
from app.services.email.outbox import OPTED_OUT
from app.services.email.providers import EmailProvider, OffProvider, OutgoingEmail, SendError, get_provider
from app.services.email.templates import render

logger = logging.getLogger("office.email")

BACKOFF_SECONDS = (60, 300, 1800, 7200, 21600)


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1])


def _finish(row: EmailLog, status: str, error: str | None = None) -> None:
    row.status = status
    row.error = error
    row.payload = {}                 # the content is not kept once the e-mail is done
    row.next_attempt_at = None


def deliver(session, row: EmailLog, provider: EmailProvider, now: datetime) -> str:
    """Send one queued row; returns its new status."""
    settings = get_settings()
    user = UserRepository(session, row.company_id).get(row.user_id) if row.user_id else None
    if user is None or user.status != "active":
        _finish(row, "skipped", "the user is no longer active")
    elif not row.urgent and not user.email_notifications:
        _finish(row, "skipped", OPTED_OUT)
    elif isinstance(provider, OffProvider):
        _finish(row, "skipped", "e-mail is switched off on the server")
    elif row.template == "chat_unread" and (reason := _chat_skip_reason(session, row)):
        _finish(row, "skipped", reason)
    else:
        rendered = render(row.template, user.language, row.payload, user.full_name, settings.app_link_url)
        message = OutgoingEmail(to=user.email, subject=rendered.subject, text=rendered.text, html=rendered.html,
                                idempotency_key=f"office-email-{row.id}")
        row.attempts += 1
        try:
            row.provider_message_id = provider.send(message)[:200] or None
        except SendError as error:
            if error.permanent or row.attempts >= settings.email_max_attempts:
                _finish(row, "failed", error.reason)
            else:
                row.error = error.reason
                row.next_attempt_at = now + backoff(row.attempts)
        except Exception as error:                       # never let one e-mail stop the worker
            reason = f"unexpected error ({type(error).__name__})"
            if row.attempts >= settings.email_max_attempts:
                _finish(row, "failed", reason)
            else:
                row.error = reason
                row.next_attempt_at = now + backoff(row.attempts)
        else:
            _finish(row, "sent")
            row.sent_at = now
    logger.info("e-mail #%s template=%s status=%s attempts=%s", row.id, row.template, row.status, row.attempts)
    return row.status


def _chat_skip_reason(session, row: EmailLog) -> str | None:
    from app.routers.chat import chat_email_skip_reason      # the chat decides (online? already read?)
    return chat_email_skip_reason(session, row)


def process_due(provider: EmailProvider | None = None, now: datetime | None = None, per_company: int = 50) -> dict:
    """One round: send what is due. Returns ``{status: count}``."""
    provider = provider or get_provider()
    counts: dict[str, int] = {}
    with transaction(None) as session:
        companies = list(session.execute(text("SELECT email_due_companies(:n)"), {"n": 200}).scalars())
    for company_id in companies:
        for _ in range(per_company):
            moment = now or datetime.now(UTC)
            with transaction(company_id) as session:
                row = session.scalars(
                    select(EmailLog).where(EmailLog.company_id == company_id, EmailLog.status == "queued",
                                           or_(EmailLog.next_attempt_at.is_(None), EmailLog.next_attempt_at <= moment))
                    .order_by(EmailLog.id).limit(1).with_for_update(skip_locked=True)).first()
                if row is None:
                    break
                status = deliver(session, row, provider, moment)
                key = status if status != "queued" else "retry"
                counts[key] = counts.get(key, 0) + 1
    return counts


class EmailWorker:
    """Runs :func:`process_due` every few seconds on a background thread."""

    def __init__(self, interval: float):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="email-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                process_due()
            except Exception as error:
                logger.warning("e-mail round failed (%s)", type(error).__name__)
