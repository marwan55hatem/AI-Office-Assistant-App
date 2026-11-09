"""Mail providers behind one small interface, chosen by ``EMAIL_PROVIDER``.

Every provider takes an :class:`OutgoingEmail` and returns the provider's message id, or
raises :class:`SendError`. ``permanent=True`` means "retrying will not help" (a refused
address, a bad key); anything else is retried later by the worker.

Nothing here logs an address or a body. Error texts are built by this module (status
codes and kinds only), because a provider's own error text can repeat the address.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger("office.email")


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str
    #: lets a provider drop a repeat of the same e-mail (the worker passes the log row id)
    idempotency_key: str | None = None


class SendError(Exception):
    def __init__(self, reason: str, permanent: bool = False):
        super().__init__(reason)
        self.reason = reason[:200]
        self.permanent = permanent


def mask(address: str) -> str:
    """``a***@example.com`` -- enough to tell addresses apart in a log, not to read one."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


class EmailProvider:
    name = "base"

    def send(self, message: OutgoingEmail) -> str:              # pragma: no cover - interface
        raise NotImplementedError


class OffProvider(EmailProvider):
    """E-mail is switched off: nothing is sent (the log row is marked 'skipped')."""
    name = "off"


class ConsoleProvider(EmailProvider):
    """Development: pretend to send, log the subject and a masked address only."""
    name = "console"

    def send(self, message: OutgoingEmail) -> str:
        logger.info("e-mail (console, not sent) to=%s subject_chars=%d", mask(message.to), len(message.subject))
        return f"console-{uuid.uuid4().hex[:12]}"


@dataclass
class FakeProvider(EmailProvider):
    """Tests: keeps the messages in memory; can be told to fail."""
    name = "fake"
    sent: list[OutgoingEmail] = field(default_factory=list)
    #: a list of SendError to raise, one per call, before succeeding
    failures: list[SendError] = field(default_factory=list)

    def send(self, message: OutgoingEmail) -> str:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(message)
        return f"fake-{len(self.sent)}"


def _http_error(provider: str, response: httpx.Response) -> SendError:
    code = response.status_code
    transient = code == 429 or code >= 500 or code == 408
    return SendError(f"{provider} answered HTTP {code}", permanent=not transient)


class _HttpProvider(EmailProvider):
    url = ""

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=15.0)

    def _post(self, payload: dict, headers: dict) -> httpx.Response:
        try:
            response = self.client.post(self.url, json=payload, headers=headers)
        except httpx.HTTPError as error:
            raise SendError(f"{self.name} could not be reached ({type(error).__name__})") from None
        if response.status_code >= 300:
            raise _http_error(self.name, response)
        return response


class ResendProvider(_HttpProvider):
    """https://resend.com/docs/api-reference/emails/send-email"""
    name = "resend"
    url = "https://api.resend.com/emails"

    def send(self, message: OutgoingEmail) -> str:
        key = self.settings.resend_api_key
        if key is None or not key.get_secret_value():
            raise SendError("RESEND_API_KEY is not set", permanent=True)
        payload = {"from": self.settings.email_from, "to": [message.to], "subject": message.subject,
                   "text": message.text, "html": message.html}
        if self.settings.email_reply_to:
            payload["reply_to"] = self.settings.email_reply_to
        headers = {"Authorization": f"Bearer {key.get_secret_value()}"}
        if message.idempotency_key:
            headers["Idempotency-Key"] = message.idempotency_key
        return str(self._post(payload, headers).json().get("id", ""))


class SendGridProvider(_HttpProvider):
    """https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send"""
    name = "sendgrid"
    url = "https://api.sendgrid.com/v3/mail/send"

    def send(self, message: OutgoingEmail) -> str:
        key = self.settings.sendgrid_api_key
        if key is None or not key.get_secret_value():
            raise SendError("SENDGRID_API_KEY is not set", permanent=True)
        name, address = parseaddr(self.settings.email_from)
        payload = {"personalizations": [{"to": [{"email": message.to}]}],
                   "from": {"email": address, **({"name": name} if name else {})},
                   "subject": message.subject,
                   "content": [{"type": "text/plain", "value": message.text},
                               {"type": "text/html", "value": message.html}]}
        if self.settings.email_reply_to:
            payload["reply_to"] = {"email": self.settings.email_reply_to}
        response = self._post(payload, {"Authorization": f"Bearer {key.get_secret_value()}"})
        return response.headers.get("X-Message-Id", "")


class SmtpProvider(EmailProvider):
    name = "smtp"

    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, message: OutgoingEmail) -> str:
        s = self.settings
        if not s.smtp_host:
            raise SendError("SMTP_HOST is not set", permanent=True)
        mail = EmailMessage()
        mail["From"] = s.email_from
        mail["To"] = message.to
        mail["Subject"] = message.subject
        if s.email_reply_to:
            mail["Reply-To"] = s.email_reply_to
        message_id = make_msgid(domain=parseaddr(s.email_from)[1].partition("@")[2] or None)
        mail["Message-ID"] = message_id
        mail.set_content(message.text)
        mail.add_alternative(message.html, subtype="html")
        context = ssl.create_default_context()
        try:
            if s.smtp_port == 465:
                server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=context)
            else:
                server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
            with server:
                if s.smtp_port != 465 and s.smtp_starttls:
                    server.starttls(context=context)
                if s.smtp_username:
                    password = s.smtp_password.get_secret_value() if s.smtp_password else ""
                    server.login(s.smtp_username, password)
                server.send_message(mail)
        except smtplib.SMTPAuthenticationError:
            raise SendError("SMTP sign-in was refused", permanent=True) from None
        except smtplib.SMTPRecipientsRefused:
            raise SendError("SMTP refused the recipient", permanent=True) from None
        except smtplib.SMTPResponseException as error:
            raise SendError(f"SMTP answered {error.smtp_code}", permanent=500 <= error.smtp_code < 600) from None
        except (smtplib.SMTPException, OSError) as error:
            raise SendError(f"SMTP could not be reached ({type(error).__name__})") from None
        return message_id


_override: EmailProvider | None = None


def set_provider(provider: EmailProvider | None) -> None:
    """Tests: use this provider instead of the configured one (``None`` = back to config)."""
    global _override
    _override = provider


def get_provider(settings: Settings | None = None) -> EmailProvider:
    if _override is not None:
        return _override
    settings = settings or get_settings()
    choice = settings.email_provider
    if choice == "fake" and settings.environment == "production":
        raise RuntimeError("EMAIL_PROVIDER=fake is for tests only")
    simple = {"off": OffProvider, "console": ConsoleProvider, "fake": FakeProvider}
    if choice in simple:
        return simple[choice]()
    return {"smtp": SmtpProvider, "resend": ResendProvider, "sendgrid": SendGridProvider}[choice](settings)
