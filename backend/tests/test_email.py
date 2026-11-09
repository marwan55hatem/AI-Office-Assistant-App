"""Phase 5: e-mail notifications -- triggers, preferences, the queue/worker, templates, providers."""
import smtplib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import get_settings
from app.services.email import templates
from app.services.email.providers import (FakeProvider, OffProvider, OutgoingEmail, ResendProvider, SendError,
                                          SendGridProvider, SmtpProvider, mask)
from app.services.email.worker import process_due
from tests.conftest import add_active_employee, auth, register

LINK = "https://app.example.test"


@pytest.fixture
def team(client):
    boss = register(client, "Acme", "boss@acme-corp.com", "Sara Boss")
    anna, anna_id = add_active_employee(client, boss, "anna@acme-corp.com", "Anna Hamdan")
    ben, ben_id = add_active_employee(client, boss, "ben@acme-corp.com", "Ben Okafor")
    return {"boss": boss, "anna": anna, "ben": ben, "anna_id": anna_id, "ben_id": ben_id}


def rows(owner_engine):
    with owner_engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(
            "SELECT e.*, u.email AS to_email FROM email_log e LEFT JOIN users u ON u.id = e.user_id ORDER BY e.id"))]


def urgent_task(client, team, title="Fix the server", **extra):
    response = client.post("/tasks", json={"title": title, "user_id": team["anna_id"], "priority": "urgent", **extra},
                           headers=auth(team["boss"]))
    assert response.status_code == 201, response.text
    return response.json()


def meeting(client, team, attendees, **extra):
    event = client.post("/calendar", json={"title": "Planning", "event_date": "2026-11-12", "start_time": "10:00:00",
                                           "end_time": "11:00:00", **extra}, headers=auth(team["boss"])).json()
    client.put(f"/calendar/{event['id']}/attendees", json={"user_ids": attendees}, headers=auth(team["boss"]))
    return event


# ---------------------------------------------------------------- triggers
def test_an_urgent_task_from_the_manager_is_emailed(client, team, owner_engine):
    urgent_task(client, team, deadline_date="2026-11-12", deadline_time="17:00:00")
    [row] = rows(owner_engine)
    assert (row["template"], row["status"], row["urgent"], row["to_email"]) == ("task_urgent", "queued", True,
                                                                               "anna@acme-corp.com")
    fake = FakeProvider()
    assert process_due(fake) == {"sent": 1}
    [mail] = fake.sent
    assert mail.to == "anna@acme-corp.com" and mail.subject == "Urgent task: Fix the server"
    for part in (mail.text, mail.html):
        assert "Fix the server" in part and "Sara Boss" in part and "Thu 12 Nov 2026, 17:00" in part
        assert f"{LINK}/tasks" in part
    [row] = rows(owner_engine)
    assert row["status"] == "sent" and row["attempts"] == 1 and row["sent_at"] and row["provider_message_id"] == "fake-1"
    assert row["payload"] == {}                    # the content is not kept after sending
    assert "error" not in row or row["error"] is None


def test_normal_and_self_made_tasks_are_not_emailed(client, team, owner_engine):
    client.post("/tasks", json={"title": "Normal", "user_id": team["anna_id"]}, headers=auth(team["boss"]))
    client.post("/tasks", json={"title": "My own urgent", "priority": "urgent"}, headers=auth(team["anna"]))
    client.post("/tasks", json={"title": "Boss's own", "priority": "urgent"}, headers=auth(team["boss"]))
    assert rows(owner_engine) == []


def test_meeting_invite_change_and_cancel(client, team, owner_engine):
    me = client.get("/auth/me", headers=auth(team["boss"])).json()["user"]["id"]
    event = meeting(client, team, [team["anna_id"], team["ben_id"], me])          # the organiser is not e-mailed
    assert sorted(r["to_email"] for r in rows(owner_engine)) == ["anna@acme-corp.com", "ben@acme-corp.com"]
    assert {r["template"] for r in rows(owner_engine)} == {"meeting_invite"}

    client.patch(f"/calendar/{event['id']}", json={"description": "agenda"}, headers=auth(team["boss"]))
    client.patch(f"/calendar/{event['id']}", json={"title": "Planning"}, headers=auth(team["boss"]))   # same value
    assert len(rows(owner_engine)) == 2                                            # neither is worth an e-mail

    client.patch(f"/calendar/{event['id']}", json={"start_time": "14:00:00", "end_time": "15:00:00"},
                 headers=auth(team["boss"]))
    changed = [r for r in rows(owner_engine) if r["template"] == "meeting_changed"]
    assert len(changed) == 2 and changed[0]["payload"]["start"] == "14:00:00"

    client.put(f"/calendar/{event['id']}/attendees", json={"user_ids": [team["anna_id"]]}, headers=auth(team["boss"]))
    removed = [r for r in rows(owner_engine) if r["template"] == "meeting_cancelled"]
    assert [r["to_email"] for r in removed] == ["ben@acme-corp.com"]

    client.delete(f"/calendar/{event['id']}", headers=auth(team["boss"]))
    cancelled = [r for r in rows(owner_engine) if r["template"] == "meeting_cancelled"]
    assert [r["to_email"] for r in cancelled] == ["ben@acme-corp.com", "anna@acme-corp.com"]

    fake = FakeProvider()
    assert process_due(fake) == {"sent": 6}
    cancel_mail = fake.sent[-1]
    assert cancel_mail.subject == "Meeting cancelled: Planning" and LINK not in cancel_mail.text   # nothing to open
    assert "Thu 12 Nov 2026, 14:00–15:00" in cancel_mail.text


# ---------------------------------------------------------------- preferences
def test_preferences_endpoint(client, team):
    response = client.patch("/users/me/preferences", json={"email_notifications": False, "language": "ar"},
                            headers=auth(team["anna"]))
    assert response.status_code == 200
    assert (response.json()["email_notifications"], response.json()["language"]) == (False, "ar")
    me = client.get("/auth/me", headers=auth(team["anna"])).json()["user"]
    assert (me["email_notifications"], me["language"]) == (False, "ar")
    assert client.patch("/users/me/preferences", json={"language": "fr"}, headers=auth(team["anna"])).status_code == 422
    assert client.patch("/users/me/preferences", json={"email": "x@y.com"}, headers=auth(team["anna"])).status_code == 422


def test_turning_optional_emails_off_keeps_urgent_ones(client, team, owner_engine):
    client.patch("/users/me/preferences", json={"email_notifications": False}, headers=auth(team["anna"]))
    meeting(client, team, [team["anna_id"]])
    urgent_task(client, team)
    by_template = {r["template"]: r for r in rows(owner_engine)}
    assert by_template["meeting_invite"]["status"] == "skipped"
    assert by_template["meeting_invite"]["error"] == "turned off by the user"
    assert by_template["meeting_invite"]["payload"] == {}
    fake = FakeProvider()
    assert process_due(fake) == {"sent": 1}
    assert fake.sent[0].subject.startswith("Urgent task")


def test_turning_off_also_stops_emails_already_queued(client, team, owner_engine):
    meeting(client, team, [team["anna_id"]])
    client.patch("/users/me/preferences", json={"email_notifications": False}, headers=auth(team["anna"]))
    fake = FakeProvider()
    assert process_due(fake) == {"skipped": 1} and fake.sent == []


def test_a_disabled_employee_gets_nothing(client, team, owner_engine):
    urgent_task(client, team)
    client.patch(f"/users/{team['anna_id']}/status", json={"status": "disabled"}, headers=auth(team["boss"]))
    assert process_due(FakeProvider()) == {"skipped": 1}
    assert rows(owner_engine)[0]["error"] == "the user is no longer active"


def test_arabic_emails(client, team):
    client.patch("/users/me/preferences", json={"language": "ar"}, headers=auth(team["anna"]))
    urgent_task(client, team, deadline_date="2026-11-12")
    fake = FakeProvider()
    process_due(fake)
    mail = fake.sent[0]
    assert mail.subject == "مهمة عاجلة: Fix the server"
    assert 'dir="rtl"' in mail.html and 'lang="ar"' in mail.html
    assert "الخميس 12 نوفمبر 2026" in mail.text and "كلّفك Sara Boss" in mail.text


# ---------------------------------------------------------------- the worker
def make_due(owner_engine):
    with owner_engine.begin() as c:
        c.execute(text("UPDATE email_log SET next_attempt_at = now() - interval '1 second' WHERE status = 'queued'"))


def test_a_failed_send_is_retried_later(client, team, owner_engine):
    urgent_task(client, team)
    fake = FakeProvider(failures=[SendError("resend answered HTTP 503")])
    assert process_due(fake) == {"retry": 1}
    [row] = rows(owner_engine)
    assert row["status"] == "queued" and row["attempts"] == 1 and row["error"] == "resend answered HTTP 503"
    assert row["next_attempt_at"] > datetime.now(UTC) + timedelta(seconds=50)       # first retry after a minute
    assert row["payload"]["title"] == "Fix the server"                             # still needed for the retry
    assert process_due(fake) == {}                                                 # not due yet
    make_due(owner_engine)
    assert process_due(fake) == {"sent": 1}
    [row] = rows(owner_engine)
    assert row["status"] == "sent" and row["attempts"] == 2 and row["error"] is None


def test_a_permanent_failure_is_not_retried(client, team, owner_engine):
    urgent_task(client, team)
    assert process_due(FakeProvider(failures=[SendError("refused", permanent=True)])) == {"failed": 1}
    [row] = rows(owner_engine)
    assert (row["status"], row["attempts"], row["payload"], row["next_attempt_at"]) == ("failed", 1, {}, None)


def test_giving_up_after_the_last_attempt(client, team, owner_engine):
    urgent_task(client, team)
    attempts = get_settings().email_max_attempts
    fake = FakeProvider(failures=[SendError("timeout")] * attempts)
    for _ in range(attempts):
        process_due(fake)
        make_due(owner_engine)
    [row] = rows(owner_engine)
    assert (row["status"], row["attempts"], row["error"]) == ("failed", attempts, "timeout")


def test_an_unexpected_error_does_not_stop_the_round(client, team, owner_engine):
    class Broken(FakeProvider):
        def send(self, message):
            if "anna" in message.to:
                raise RuntimeError("boom anna@acme-corp.com")
            return super().send(message)

    meeting(client, team, [team["anna_id"], team["ben_id"]])
    fake = Broken()
    assert process_due(fake) == {"retry": 1, "sent": 1}
    anna = next(r for r in rows(owner_engine) if r["to_email"] == "anna@acme-corp.com")
    assert anna["error"] == "unexpected error (RuntimeError)"                     # no address in the log


def test_off_provider_records_skipped(client, team, owner_engine):
    urgent_task(client, team)
    assert process_due(OffProvider()) == {"skipped": 1}
    assert rows(owner_engine)[0]["error"] == "e-mail is switched off on the server"


def test_the_worker_serves_every_company(client, team, owner_engine):
    other = register(client, "Globex", "boss@globex-corp.com", "Gil")
    _tokens, gina = add_active_employee(client, other, "gina@globex-corp.com", "Gina")
    urgent_task(client, team)
    client.post("/tasks", json={"title": "Globex job", "user_id": gina, "priority": "urgent"}, headers=auth(other))
    fake = FakeProvider()
    assert process_due(fake) == {"sent": 2}
    assert sorted(m.to for m in fake.sent) == ["anna@acme-corp.com", "gina@globex-corp.com"]


# ---------------------------------------------------------------- the log endpoint
def test_managers_see_the_log_without_addresses(client, team):
    urgent_task(client, team)
    process_due(FakeProvider())
    log = client.get("/email-log", headers=auth(team["boss"])).json()
    assert len(log) == 1 and log[0]["status"] == "sent" and log[0]["template"] == "task_urgent"
    assert "@" not in str(log)
    assert client.get("/email-log", params={"status": "failed"}, headers=auth(team["boss"])).json() == []
    assert client.get("/email-log", headers=auth(team["anna"])).status_code == 403
    other = register(client, "Globex", "boss@globex-corp.com", "Gil")
    assert client.get("/email-log", headers=auth(other)).json() == []               # another company sees nothing


# ---------------------------------------------------------------- templates
@pytest.mark.parametrize("language", templates.LANGUAGES)
@pytest.mark.parametrize("template", templates.TEMPLATES)
def test_every_template_renders(template, language):
    payload = {"title": "<b>Q4</b> & plans", "who": "Sara <Boss>", "date": "2026-11-12", "time": "09:30:00",
               "start": "09:30:00", "end": None}
    out = templates.render(template, language, payload, "Anna", LINK)
    assert out.subject and "\n" not in out.subject
    assert "<b>Q4</b>" not in out.html and "Sara <Boss>" not in out.html        # user text is escaped in HTML
    assert out.html.startswith("<!DOCTYPE html>") and f'lang="{language}"' in out.html
    assert "<" not in out.text.replace("Sara <Boss>", "").replace("<b>Q4</b>", "")  # the text part has no markup


def test_unknown_template_or_language():
    with pytest.raises(ValueError):
        templates.render("nope", "en", {}, "A", LINK)
    assert templates.render("test", "fr", {}, "A", LINK).subject == "Office Assistant test e-mail"


def test_dates():
    from datetime import date
    assert templates.format_day(date(2026, 11, 9), "en") == "Mon 9 Nov 2026"
    assert templates.format_day(date(2026, 11, 9), "ar") == "الاثنين 9 نوفمبر 2026"
    assert templates.format_when(None, None, None, "en", "no_deadline") == "No deadline"
    assert templates.format_when("2026-11-09", None, None, "en", "all_day") == "Mon 9 Nov 2026 (All day)"


# ---------------------------------------------------------------- providers
MAIL = OutgoingEmail(to="anna@acme-corp.com", subject="Hi", text="t", html="<p>h</p>", idempotency_key="office-email-7")


def http_provider(cls, handler, **settings):
    s = get_settings().model_copy(update={"resend_api_key": SecretStr("re_test"), "sendgrid_api_key": SecretStr("SG.test"),
                                          "email_from": "Office <no-reply@acme.test>", **settings})
    return cls(s, httpx.Client(transport=httpx.MockTransport(handler)))


def test_resend_request_and_errors():
    seen = {}

    def ok(request):
        seen["auth"] = request.headers["authorization"]
        seen["key"] = request.headers["idempotency-key"]
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"id": "re-123"})

    assert http_provider(ResendProvider, ok).send(MAIL) == "re-123"
    assert seen["auth"] == "Bearer re_test" and seen["key"] == "office-email-7"
    assert '"to":["anna@acme-corp.com"]' in seen["body"].replace(" ", "")
    for code, permanent in ((429, False), (503, False), (422, True), (401, True)):
        with pytest.raises(SendError) as error:
            http_provider(ResendProvider, lambda r, c=code: httpx.Response(c, text="bad anna@acme-corp.com")).send(MAIL)
        assert error.value.permanent is permanent and "anna" not in error.value.reason
    with pytest.raises(SendError) as error:
        http_provider(ResendProvider, ok, resend_api_key=None).send(MAIL)
    assert error.value.permanent


def test_resend_network_error_is_transient():
    def down(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(SendError) as error:
        http_provider(ResendProvider, down).send(MAIL)
    assert not error.value.permanent


def test_sendgrid_request():
    seen = {}

    def ok(request):
        seen["body"] = request.read().decode()
        return httpx.Response(202, headers={"X-Message-Id": "sg-9"})

    assert http_provider(SendGridProvider, ok).send(MAIL) == "sg-9"
    assert '"from":{"email":"no-reply@acme.test","name":"Office"}' in seen["body"].replace(" ", "")


class FakeSMTP:
    instances = []
    fail = None

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))
        if FakeSMTP.fail:
            raise FakeSMTP.fail

    def send_message(self, mail):
        self.calls.append(("send", mail["To"], mail.get_content_type()))


def test_smtp(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    s = get_settings().model_copy(update={"smtp_host": "smtp.example.test", "smtp_username": "bot",
                                          "smtp_password": SecretStr("pw"), "email_from": "Office <no-reply@acme.test>"})
    message_id = SmtpProvider(s).send(MAIL)
    server = FakeSMTP.instances[-1]
    assert message_id.endswith("@acme.test>")
    assert server.calls == ["starttls", ("login", "bot"), ("send", "anna@acme-corp.com", "multipart/alternative")]
    FakeSMTP.fail = smtplib.SMTPAuthenticationError(535, b"no")
    with pytest.raises(SendError) as error:
        SmtpProvider(s).send(MAIL)
    FakeSMTP.fail = None
    assert error.value.permanent and error.value.reason == "SMTP sign-in was refused"
    with pytest.raises(SendError) as error:
        SmtpProvider(s.model_copy(update={"smtp_host": None})).send(MAIL)
    assert error.value.permanent


def test_mask_and_settings_validation():
    assert mask("anna@acme-corp.com") == "a***@acme-corp.com" and mask("nope") == "***"
    from pydantic import ValidationError

    from app.core.config import Settings
    base = get_settings().model_dump()
    with pytest.raises(ValidationError):
        Settings(**{**base, "email_provider": "pigeon"})
    with pytest.raises(ValidationError):
        Settings(**{**base, "app_link_url": "javascript:alert(1)"})
