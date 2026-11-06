"""Phase 4: which program was in front -- captured as a name only, counted per second at the
desk and sent with the session. Window titles must never be part of it."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")     # no real window, whatever test runs first

from cloud.outbox import Outbox  # noqa: E402
from cloud.remote_db import RemoteDatabase
from detection.app_names import OTHER, active_app_name, display_name
from detection.categories import SCREEN_DISTRACTION, SCREEN_IDLE, SCREEN_NEUTRAL, SCREEN_PRODUCTIVE
from detection.session import SessionState
from tests.test_cloud_client import FakeServer, make_api


# ---------------------------------------------------------------- names
@pytest.mark.parametrize("executable, expected", [
    (r"C:\Program Files\Google\Chrome\Application\chrome.exe", "Chrome"),
    ("msedge.exe", "Edge"), (r"C:\Windows\explorer.exe", "File Explorer"), ("WINWORD.EXE", "Word"),
    ("Code.exe", "VS Code"), ("my_custom-tool.exe", "My Custom Tool"), ("", ""), (None, ""),
    ("ALLCAPS.EXE", "Allcaps"),
])
def test_display_names(executable, expected):
    assert display_name(executable) == expected


def test_display_names_are_always_short_and_clean():
    name = display_name("x" * 500 + ".exe")
    assert len(name) <= 80 and "\x00" not in display_name("bad\x00name.exe")


def test_unknown_or_missing_windows_give_empty_or_other(monkeypatch):
    assert active_app_name(0) == ""
    monkeypatch.setattr("detection.app_names.process_image_path", lambda hwnd: "")
    assert active_app_name(12345) == OTHER                      # a protected program: counted, but not named


def test_the_real_foreground_window_has_a_name():
    pytest.importorskip("win32gui")
    if os.name != "nt":
        pytest.skip("Windows only")
    from detection.screen_monitor import ScreenMonitor

    sample = ScreenMonitor().sample_with_timer()
    assert set(sample) >= {"title", "category", "app"} and isinstance(sample["app"], str)


# ---------------------------------------------------------------- counting
def _state():
    state = SessionState("s", "u")
    state.camera_ready = True
    state.person = True
    return state


def _seconds(state, app, category, seconds, **flags):
    state.app_name, state.screen_category = app, category
    state.input_idle = flags.get("idle", False)
    state.phone = flags.get("phone", False)
    state.person = flags.get("person", True)
    for _ in range(seconds):
        state.tick()


def test_apps_are_counted_only_while_at_the_desk():
    state = _state()
    _seconds(state, "Code", SCREEN_PRODUCTIVE, 10)                       # focus
    _seconds(state, "Chrome", SCREEN_DISTRACTION, 4)                     # distracted (window)
    _seconds(state, "Code", SCREEN_PRODUCTIVE, 3, phone=True)            # distracted (phone), still at the desk
    _seconds(state, "Code", SCREEN_PRODUCTIVE, 5, idle=True)             # away: no input for 90 s
    _seconds(state, "Code", SCREEN_PRODUCTIVE, 5, person=False)          # away: nobody there
    _seconds(state, "Notes", SCREEN_IDLE, 5)                             # idle screen
    by_name = {row["name"]: row for row in state.apps_snapshot()}
    assert by_name["Code"]["seconds"] == 13 and by_name["Chrome"]["seconds"] == 4
    assert "Notes" not in by_name
    assert state.focus_seconds + state.distraction_seconds + state.away_seconds == 10 + 4 + 3 + 5 + 5 + 5


def test_snapshot_merges_categories_and_orders_by_use():
    state = _state()
    _seconds(state, "Chrome", SCREEN_NEUTRAL, 6)
    _seconds(state, "Chrome", SCREEN_DISTRACTION, 9)                     # mostly on a video site
    _seconds(state, "Code", SCREEN_PRODUCTIVE, 20)
    rows = state.apps_snapshot()
    assert [(r["name"], r["category"], r["seconds"]) for r in rows] == [("Code", "productive", 20),
                                                                         ("Chrome", "distraction", 15)]
    assert len(state.apps_snapshot(limit=1)) == 1


def test_an_unnamed_window_is_not_counted():
    state = _state()
    _seconds(state, "", SCREEN_PRODUCTIVE, 5)
    assert state.apps_snapshot() == []


# ---------------------------------------------------------------- the outbox and the wire
def test_outbox_keeps_the_highest_seconds_per_app(tmp_path):
    outbox = Outbox(str(tmp_path / "o.db"))
    outbox.start_session("s-1", "2026-11-05")
    outbox.update_session("s-1", apps=[{"name": "Code", "category": "productive", "seconds": 30}])
    outbox.update_session("s-1", apps=[{"name": "Code", "category": "productive", "seconds": 20},     # an older value
                                       {"name": "Chrome", "category": "neutral", "seconds": 5}])
    body = json.loads(outbox._db.execute("SELECT body FROM pending_sessions").fetchone()[0])
    assert {a["name"]: a["seconds"] for a in body["apps"]} == {"Code": 30, "Chrome": 5}
    outbox.close()


def test_apps_reach_the_server_and_titles_do_not(tmp_path):
    server = FakeServer()
    api = make_api(server)
    db = RemoteDatabase(api, outbox_path=str(tmp_path / "o.db"), start_sync=False)
    db.sign_in("w@corp.com", "right password")
    session_id = db.create_session("u-1")
    state = _state()
    state.screen_title = "Salary review 2026 - confidential.docx - Word"        # must never be sent
    _seconds(state, "Word", SCREEN_PRODUCTIVE, 12)
    db.update_session_progress(session_id, state.focus_seconds, state.away_seconds, apps=state.apps_snapshot())
    db.end_session(session_id, state.focus_seconds, state.away_seconds, apps=state.apps_snapshot())
    assert db.outbox.flush(api)
    sent = server.sync_batches[-1]["sessions"][0]
    assert sent["apps"] == [{"name": "Word", "category": "productive", "seconds": 12}]
    assert "Salary" not in json.dumps(server.sync_batches) and "confidential" not in json.dumps(server.sync_batches)
    db.outbox.close()


def test_the_local_database_accepts_the_same_calls(db, marwan):
    session_id = db.create_session(marwan["id"])
    db.update_session_progress(session_id, 5, 1, apps=[{"name": "Code", "category": "productive", "seconds": 5}])
    db.end_session(session_id, 6, 1, apps=[{"name": "Code", "category": "productive", "seconds": 6}])
    assert db.get_session(session_id)["focus_seconds"] == 6


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])        # kept alive by the fixture


def test_the_session_page_says_what_goes_online(qt_app, db, marwan, remote_like):
    from PyQt5.QtWidgets import QLabel

    from ui.employee_screen import SessionPage

    online, local = SessionPage(user=marwan, db=remote_like), SessionPage(user=marwan, db=db)
    texts = lambda page: " ".join(label.text() for label in page.findChildren(QLabel))      # noqa: E731
    assert "app names go to your company" in texts(online) and "camera images never leave this PC" in texts(online)
    assert "stored locally" in texts(local)


@pytest.fixture
def remote_like(tmp_path):
    api = make_api(FakeServer())
    db = RemoteDatabase(api, outbox_path=str(tmp_path / "o.db"), start_sync=False)
    yield db
    db.outbox.close()
