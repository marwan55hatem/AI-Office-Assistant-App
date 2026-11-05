"""The online client: API client, offline outbox, RemoteDatabase and the offline banner.

No server is needed: requests go to an in-memory fake (httpx.MockTransport).
"""
import inspect
import json
import os
import re
from pathlib import Path

import httpx
import pytest

from cloud.api import ApiClient, ApiError, Offline, SessionExpired
from cloud.credentials import MemoryCredentialStore
from cloud.outbox import Outbox
from cloud.remote_db import NO_CONNECTION, RemoteDatabase

ROOT = Path(__file__).resolve().parents[1]
TOKENS = {"access_token": "access-1", "refresh_token": "refresh-1", "token_type": "bearer", "expires_in": 900}
ME = {"user": {"id": "u-1", "email": "w@corp.com", "full_name": "Wendy", "role": "employee", "status": "active",
               "created_at": "2026-11-01T08:00:00Z"},
      "company": {"id": "c-1", "name": "Corp", "join_code": None}}


class FakeServer:
    """Answers like the API; ``down`` makes every request fail like a dropped network."""

    def __init__(self):
        self.down = False
        self.calls = []
        self.access = "access-1"
        self.sync_batches = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("no route", request=request)
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body))
        if path == "/auth/login":
            return httpx.Response(200, json=TOKENS) if body["password"] == "right password" else \
                httpx.Response(401, json={"detail": "Wrong e-mail or password"})
        if path == "/auth/refresh":
            if body["refresh_token"] == "revoked":
                return httpx.Response(401, json={"detail": "The session expired, please sign in again"})
            self.access = "access-2"
            return httpx.Response(200, json={**TOKENS, "access_token": "access-2", "refresh_token": "refresh-2"})
        if path == "/auth/logout":
            return httpx.Response(204)
        if request.headers.get("Authorization") != f"Bearer {self.access}":
            return httpx.Response(401, json={"detail": "Not signed in"})
        if path == "/auth/me":
            return httpx.Response(200, json=ME)
        if path == "/sessions/sync":
            self.sync_batches.append(body)
            return httpx.Response(200, json={"sessions": len(body["sessions"]), "events": len(body["events"])})
        if path == "/tasks" and method == "GET":
            return httpx.Response(200, json=[{"id": "t-1", "user_id": "u-1", "assigned_by": None, "title": "Report",
                                              "description": None, "priority": "urgent", "is_done": False,
                                              "deadline_date": "2030-01-31", "deadline_time": "17:00:00",
                                              "created_at": "2026-11-01T08:00:00Z", "completed_at": None}])
        return httpx.Response(404, json={"detail": "Not found"})


@pytest.fixture
def server():
    return FakeServer()


def make_api(server, credentials=None):
    http = httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(server))
    return ApiClient("http://api.test", http=http, credentials=credentials or MemoryCredentialStore())


@pytest.fixture
def remote(server, tmp_path):
    api = make_api(server)
    db = RemoteDatabase(api, outbox_path=str(tmp_path / "outbox.db"), start_sync=False)
    yield db
    db.outbox.close()


# ---------------------------------------------------------------- API client
def test_login_remembers_only_the_refresh_token(server):
    store = MemoryCredentialStore()
    api = make_api(server, store)
    assert api.login("w@corp.com", "right password")["user"]["full_name"] == "Wendy"
    assert store.secret == "refresh-1"                      # never the password
    api.logout()
    assert store.secret is None


def test_login_without_remember_stores_nothing(server):
    store = MemoryCredentialStore()
    make_api(server, store).login("w@corp.com", "right password", remember=False)
    assert store.secret is None


def test_wrong_password_raises_the_servers_message(server):
    with pytest.raises(ApiError, match="Wrong e-mail or password"):
        make_api(server).login("w@corp.com", "nope")


def test_expired_access_token_is_refreshed_once(server):
    api = make_api(server)
    api.login("w@corp.com", "right password")
    server.access = "access-2"                              # the server rotated: access-1 is now refused
    assert api.get("/auth/me")["user"]["id"] == "u-1"
    assert [c[1] for c in server.calls].count("/auth/refresh") == 1


def test_failed_refresh_ends_the_session(server):
    store = MemoryCredentialStore("revoked")
    api = make_api(server, store)
    expired = []
    api.on_session_expired(lambda: expired.append(True))
    assert api.restore() is None
    assert expired == [True] and store.secret is None and not api.signed_in


def test_network_errors_mark_the_client_offline_then_online(server):
    api = make_api(server)
    changes = []
    api.on_connection_change(changes.append)
    api.login("w@corp.com", "right password")
    server.down = True
    with pytest.raises(Offline):
        api.get("/auth/me")
    server.down = False
    api.get("/auth/me")
    assert changes == [True, False, True]


# ---------------------------------------------------------------- outbox
def test_outbox_survives_a_restart_and_sends_once(server, tmp_path):
    path = str(tmp_path / "outbox.db")
    outbox = Outbox(path)
    outbox.start_session("s-1", "2026-11-05")
    outbox.add_event("s-1", "focus")
    outbox.update_session("s-1", focus_seconds=30, away_seconds=2)
    outbox.close()

    outbox = Outbox(path)                                   # the app was closed and opened again
    api = make_api(server)
    api.login("w@corp.com", "right password")
    assert outbox.pending() == 2 and outbox.flush(api)
    sent = server.sync_batches[-1]
    assert sent["sessions"][0]["focus_seconds"] == 30 and sent["events"][0]["event_type"] == "focus"
    assert outbox.pending() == 0 and outbox.flush(api)      # nothing new: nothing sent
    assert len(server.sync_batches) == 1
    outbox.close()


def test_outbox_keeps_data_while_offline_and_counters_only_grow(server, tmp_path):
    outbox = Outbox(str(tmp_path / "outbox.db"))
    api = make_api(server)
    api.login("w@corp.com", "right password")
    outbox.start_session("s-1", "2026-11-05")
    server.down = True
    with pytest.raises(Offline):
        outbox.flush(api)
    outbox.update_session("s-1", focus_seconds=50)
    outbox.update_session("s-1", focus_seconds=40)          # an older value never lowers it
    server.down = False
    assert outbox.flush(api)
    assert server.sync_batches[-1]["sessions"][0]["focus_seconds"] == 50
    outbox.update_session("s-1", ended=True, focus_seconds=60)
    assert outbox.flush(api) and "ended_at" in server.sync_batches[-1]["sessions"][0]
    assert outbox.pending() == 0
    outbox.close()


def test_outbox_stores_no_titles_or_secrets(tmp_path):
    path = tmp_path / "outbox.db"
    outbox = Outbox(str(path))
    outbox.start_session("s-1", "2026-11-05")
    outbox.add_event("s-1", "distraction")
    outbox.close()
    raw = path.read_bytes()
    assert b"password" not in raw and b"token" not in raw


# ---------------------------------------------------------------- RemoteDatabase
def test_sessions_record_offline(remote, server):
    remote.sign_in("w@corp.com", "right password")
    server.down = True
    session_id = remote.create_session("u-1")
    remote.log_event(session_id, "away")
    remote.update_session_progress(session_id, 10, 5, distraction_seconds=1)
    remote.end_session(session_id, 12, 5, distraction_seconds=1)
    assert remote.outbox.pending() == 2                    # the session and one event, waiting
    server.down = False
    assert remote.outbox.flush(remote.api)
    sent = server.sync_batches[-1]
    assert sent["sessions"][0]["id"] == session_id and sent["sessions"][0]["focus_seconds"] == 12


def test_reads_and_writes_report_no_connection(remote, server):
    remote.sign_in("w@corp.com", "right password")
    server.down = True
    assert remote.get_tasks("u-1") == []
    assert remote.get_today_totals() == {"focus_seconds": 0, "distraction_seconds": 0, "away_seconds": 0}
    assert remote.update_task_deadline("t-1", None) == (False, NO_CONNECTION)
    assert remote.add_task("u-1", "x") is None
    assert remote.sign_in("w@corp.com", "right password") == (None, NO_CONNECTION)


def test_rows_have_the_shapes_the_screens_expect(remote):
    user, _ = remote.sign_in("w@corp.com", "right password")
    assert user == {"id": "u-1", "username": "w@corp.com", "email": "w@corp.com", "full_name": "Wendy",
                    "role": "employee", "status": "approved"}
    task = remote.get_tasks("u-1")[0]
    assert task["deadline_time"] == "17:00" and task["is_done"] == 0
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", task["created_at"])


def test_the_email_cannot_be_changed_online(remote):
    remote.sign_in("w@corp.com", "right password")
    ok, message = remote.update_user_profile("u-1", full_name="Wendy", username="other@corp.com")
    assert not ok and "e-mail" in message


# ---------------------------------------------------------------- the two databases match
def _called_database_methods():
    """Every ``db.<name>(`` / ``self.db.<name>(`` in the code that runs against either database."""
    names = set()
    for folder in ("ui", "assistant", "chat", "knowledge"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.name == "selftest.py":
                continue
            names |= set(re.findall(r"\b(?:self\.)?_?db\.([a-z_]+)\(", path.read_text(encoding="utf-8")))
    names |= set(re.findall(r"\bself\.db\.([a-z_]+)\(", (ROOT / "main.py").read_text(encoding="utf-8")))
    return names


def test_remote_database_offers_every_method_the_app_calls():
    from database.db_manager import DatabaseManager

    called = _called_database_methods()
    assert len(called) > 40
    for name in sorted(called):
        assert hasattr(RemoteDatabase, name), f"RemoteDatabase lacks {name}"
        local, online = inspect.signature(getattr(DatabaseManager, name)), inspect.signature(getattr(RemoteDatabase, name))
        assert list(local.parameters)[:len(online.parameters)] == list(online.parameters), \
            f"{name}: {local} vs {online}"


def test_repository_views_work_online(remote):
    assert remote.chats.get_ai_chats.__name__ == "get_ai_chats"
    with pytest.raises(AttributeError):
        remote.chats.delete_task


# ---------------------------------------------------------------- the window
@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_offline_banner_and_disabled_pages(qt_app, db):
    from ui.employee_screen import EmployeeScreen

    user = db.get_user("marwan", "1234", "employee")
    screen = EmployeeScreen(user=user, db=db)
    screen.set_online(False)
    assert not screen.connection_banner.isHidden()
    assert not screen.sidebar._buttons["todo"].isEnabled()
    assert screen.sidebar._buttons["session"].isEnabled() and screen.sidebar._buttons["ai_helper"].isEnabled()
    screen.set_online(True)
    assert screen.connection_banner.isHidden() and screen.sidebar._buttons["todo"].isEnabled()
    screen.deleteLater()


def test_session_page_works_with_uuid_session_ids(qt_app, remote):
    from detection.session import SessionState
    from ui.employee_screen import SessionPage

    remote.sign_in("w@corp.com", "right password")
    page = SessionPage(user=remote.me, db=remote)
    page.session_id = remote.create_session("u-1")
    page.session_state = SessionState(page.session_id, "u-1")
    page.session_state.camera_ready = True
    page.session_state.person = True
    for _ in range(5):
        page._tick()                                       # five counted seconds -> one progress update
    assert remote.outbox.pending() >= 1
    page.deleteLater()


def test_sign_out_clears_the_stored_sign_in(remote):
    remote.sign_in("w@corp.com", "right password")
    remote.sign_out()
    assert remote.api.credentials.load() is None and not remote.api.signed_in
    with pytest.raises(SessionExpired):
        remote.api.get("/auth/me")


def test_closing_stops_the_sync_thread_and_sends_what_is_queued(server, tmp_path):
    """Closing the app must stop the background sender cleanly and flush the outbox."""
    api = make_api(server)
    db = RemoteDatabase(api, outbox_path=str(tmp_path / "outbox.db"), sync_interval=60)   # thread running
    db.sign_in("w@corp.com", "right password")
    session_id = db.create_session("u-1")
    db.end_session(session_id, 5, 0)
    db.close()
    assert not db.sync.is_alive()
    assert server.sync_batches and server.sync_batches[-1]["sessions"][0]["id"] == session_id
