"""Phase 6 desktop side: the Meetings page for both roles, the client calls, tray notifications."""
import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from ui.meetings_screen import MeetingsScreen, RequestCard, show_time  # noqa: E402

TZ = timezone(timedelta(hours=3))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def iso(days, hour):
    day = (datetime.now(TZ) + timedelta(days=days)).date()
    return datetime(day.year, day.month, day.day, hour, tzinfo=TZ).isoformat()


def request(status="pending", **extra):
    row = {"id": "r1", "topic": "Salary review", "note": "Before month end", "duration_minutes": 30,
           "proposed_times": [iso(2, 10), iso(3, 11)], "status": status, "chosen_time": None,
           "decline_reason": None, "reply_note": None, "calendar_event_id": None, "requested_by": "u-anna",
           "requested_by_name": "Anna Hamdan", "manager_id": None, "manager_name": None,
           "created_at": "2026-11-09T08:00:00Z", "updated_at": "2026-11-09T08:00:00Z",
           "waiting_for": {"pending": "manager", "rescheduled": "employee"}.get(status)}
    row.update(extra)
    return row


class FakeDb:
    """Stands in for RemoteDatabase: records calls, answers like the server."""
    api = object()

    def __init__(self, rows=None, fail=None):
        self.rows = rows if rows is not None else [request()]
        self.calls = []
        self.fail = fail

    def get_meeting_requests(self, status=None):
        self.calls.append(("list", status))
        return [r for r in self.rows if status in (None, r["status"]) or
                (status == "open" and r["status"] in ("pending", "rescheduled"))]

    def _answer(self, name, *args):
        self.calls.append((name, *args))
        return (False, self.fail) if self.fail else (True, {})

    def request_meeting(self, topic, times, note=None, duration_minutes=30):
        return self._answer("request", topic, times, note, duration_minutes)

    def accept_meeting_request(self, request_id, time, duration_minutes=None):
        return self._answer("accept", request_id, time)

    def decline_meeting_request(self, request_id, reason):
        return self._answer("decline", request_id, reason)

    def reschedule_meeting_request(self, request_id, times, note=None):
        return self._answer("reschedule", request_id, times, note)

    def cancel_meeting_request(self, request_id, reason=None):
        return self._answer("cancel", request_id)


def page(qapp, role, db):
    screen = MeetingsScreen(user={"id": "me", "full_name": "Me", "role": role}, db=db)
    screen.refresh()
    return screen


# ---------------------------------------------------------------- employee
def test_employee_sends_a_request_with_up_to_three_times(qapp):
    db = FakeDb(rows=[])
    screen = page(qapp, "employee", db)
    assert screen.empty_label.text() == "No open requests."
    screen.send_button.click()
    assert "topic" in screen.form_status.text() and not any(c[0] == "request" for c in db.calls)
    screen.topic_input.setText("Project plan")
    screen.note_input.setPlainText("Q1 goals")
    for _ in range(5):
        screen.times_editor.add_button.click()
    assert len(screen.times_editor.edits) == 3 and not screen.times_editor.add_button.isEnabled()
    screen.duration_combo.setCurrentIndex(screen.duration_combo.findData(60))
    screen.send_button.click()
    _name, topic, times, note, minutes = next(c for c in db.calls if c[0] == "request")
    assert (topic, note, minutes, len(times)) == ("Project plan", "Q1 goals", 60, 3)
    assert all(t.tzinfo is not None and t > datetime.now(t.tzinfo) for t in times)   # aware and in the future
    assert "Request sent" in screen.form_status.text() and screen.topic_input.text() == ""
    assert len(screen.times_editor.edits) == 1                                       # the form is reset


def test_employee_buttons_follow_the_state(qapp):
    db = FakeDb(rows=[request("pending"), request("rescheduled", id="r2", manager_name="Sara Boss",
                                                  reply_note="Away that week"),
                      request("accepted", id="r3", chosen_time=iso(5, 9))])
    screen = page(qapp, "employee", db)
    screen.filter_combo.setCurrentIndex(screen.filter_combo.findData(None))
    pending, rescheduled, accepted = screen.cards
    assert set(pending.buttons) == {"cancel"} and not pending.time_buttons           # waiting for the manager
    assert set(rescheduled.buttons) == {"accept", "cancel"} and len(rescheduled.time_buttons) == 2
    assert set(accepted.buttons) == {"cancel"} and accepted.buttons["cancel"].text() == "Cancel meeting"
    rescheduled.time_buttons[1].setChecked(True)
    rescheduled.buttons["accept"].click()
    assert ("accept", "r2", rescheduled.row["proposed_times"][1]) in db.calls
    assert "Booked for" in screen.notice.text()


def test_cancel_asks_first(qapp):
    db = FakeDb()
    screen = page(qapp, "employee", db)
    screen._confirm = lambda *a: False
    screen.cards[0].buttons["cancel"].click()
    assert not any(c[0] == "cancel" for c in db.calls)
    screen._confirm = lambda *a: True
    screen.cards[0].buttons["cancel"].click()
    assert ("cancel", "r1") in db.calls


# ---------------------------------------------------------------- manager
def test_manager_accepts_declines_and_proposes(qapp):
    db = FakeDb()
    screen = page(qapp, "manager", db)
    [card] = screen.cards
    assert set(card.buttons) == {"accept", "reschedule", "decline"} and len(card.time_buttons) == 2
    card.buttons["accept"].click()
    assert ("accept", "r1", card.row["proposed_times"][0]) in db.calls             # the first time is preselected

    screen._ask_reason = lambda *a, **k: None                                      # the dialog was closed
    screen.cards[0].buttons["decline"].click()
    assert not any(c[0] == "decline" for c in db.calls)
    screen._ask_reason = lambda *a, **k: "Let's talk in the 1:1"
    screen.cards[0].buttons["decline"].click()
    assert ("decline", "r1", "Let's talk in the 1:1") in db.calls

    new_times = [datetime.now().astimezone() + timedelta(days=4)]
    screen._ask_times = lambda: (new_times, "Travelling")
    screen.cards[0].buttons["reschedule"].click()
    assert ("reschedule", "r1", new_times, "Travelling") in db.calls


def test_manager_sees_who_and_waiting_states(qapp):
    db = FakeDb(rows=[request("rescheduled"), request("accepted", id="r3", chosen_time=iso(5, 9))])
    screen = page(qapp, "manager", db)
    screen.filter_combo.setCurrentIndex(screen.filter_combo.findData(None))
    rescheduled, accepted = screen.cards
    assert set(rescheduled.buttons) == {"reschedule", "decline"} and not rescheduled.time_buttons
    assert set(accepted.buttons) == {"cancel"}
    texts = [w.text() for w in accepted.findChildren(type(screen.notice))]
    assert any("From Anna Hamdan" in t for t in texts) and any("Booked:" in t for t in texts)


def test_a_server_refusal_is_shown(qapp):
    db = FakeDb(fail="This request is declined and cannot be changed that way")
    screen = page(qapp, "manager", db)
    screen.cards[0].buttons["accept"].click()
    assert screen.notice.text() == "This request is declined and cannot be changed that way"


def test_offline_database_shows_why(qapp):
    class LocalDb:
        pass

    screen = page(qapp, "employee", LocalDb())
    assert "online server" in screen.notice.text() and not screen.send_button.isEnabled()


def test_user_text_is_not_treated_as_markup(qapp):
    card = RequestCard(request("declined", decline_reason="<b>no</b>", waiting_for=None), manager_view=False)
    labels = [w.text() for w in card.findChildren(type(card.pill))]
    assert any("&lt;b&gt;no&lt;/b&gt;" in t for t in labels)


def test_times_are_shown_in_local_time():
    moment = datetime(2030, 1, 15, 10, 0, tzinfo=timezone.utc)
    local = moment.astimezone()
    assert show_time(moment.isoformat()) == f"{local:%a} {local.day} {local:%b %Y}, {local:%H:%M}"


# ---------------------------------------------------------------- the client and the tray
def test_client_sends_iso_times_with_an_offset(tmp_path):
    from cloud.api import ApiClient
    from cloud.credentials import MemoryCredentialStore
    from cloud.remote_db import RemoteDatabase

    seen = []

    def server(req):
        if req.url.path == "/auth/login":
            return httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "token_type": "bearer",
                                             "expires_in": 900})
        if req.url.path == "/auth/me":
            return httpx.Response(200, json={"user": {"id": "u", "email": "w@corp.com", "full_name": "W",
                                                      "role": "employee", "status": "active"}, "company": {}})
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        if req.url.path == "/meeting-requests/waiting-count":
            return httpx.Response(200, json={"waiting": 2})
        if req.url.path.endswith("/accept"):
            return httpx.Response(409, json={"detail": "This request is accepted and cannot be changed that way"})
        if req.url.path == "/meeting-requests" and req.method == "POST":
            return httpx.Response(422, json={"detail": [{"msg": "Value error, proposed times must be in the future"}]})
        return httpx.Response(200, json=[])

    api = ApiClient("http://api.test", http=httpx.Client(base_url="http://api.test",
                                                         transport=httpx.MockTransport(server)),
                    credentials=MemoryCredentialStore())
    db = RemoteDatabase(api, outbox_path=str(tmp_path / "o.db"), start_sync=False)
    try:
        api.login("w@corp.com", "pw")
        naive = datetime(2031, 3, 1, 10, 0)
        ok, message = db.request_meeting("Plan", [naive], note="")
        method, path, body = seen[-1]
        assert body["proposed_times"][0].startswith("2031-03-01T10:00:00") and body["proposed_times"][0][19] in "+-"
        assert body["note"] is None and (ok, message) == (False, "proposed times must be in the future")
        assert db.count_meeting_requests_waiting() == 2
        assert db.accept_meeting_request("r1", iso(2, 10)) == (False, "This request is accepted and cannot be "
                                                                      "changed that way")
        db.get_meeting_requests("open")
        assert seen[-1][1] == "/meeting-requests"
    finally:
        db.outbox.close()


def test_tray_shows_each_server_notification_once(qapp):
    from ui.notifications import TrayNotifier

    class Db:
        def get_today_events(self, user_id):
            return []

        def get_upcoming_deadlines(self, user_id, hours):
            return []

        def get_notifications(self, unread_only=False):
            return [{"id": 2, "title": "Meeting accepted: Plan", "body": "Thu 12 Nov 10:00"},
                    {"id": 1, "title": "Meeting request from Anna", "body": None}]

    notifier = TrayNotifier(Db())
    notifier.user_id = "me"
    first = notifier.check()
    assert first == [("Meeting request from Anna", ""), ("Meeting accepted: Plan", "Thu 12 Nov 10:00")]
    assert notifier.check() == []
    notifier.stop()


def test_a_periodic_reload_keeps_the_last_message(qapp):
    db = FakeDb()
    screen = page(qapp, "manager", db)
    screen.cards[0].buttons["accept"].click()
    message = screen.notice.text()
    screen.refresh()                                                  # the shell reloads every 30 s
    assert message.startswith("Booked for") and screen.notice.text() == message
