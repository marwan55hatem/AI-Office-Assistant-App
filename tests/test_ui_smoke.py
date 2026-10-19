"""Headless (offscreen) checks of the screens that were refactored, including injected fakes.

These need PyQt5 but no display, camera or model.  Settings are written to a temporary
``.ini`` file so the developer's real preferences are never touched.
"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt5")

from PyQt5.QtCore import QSettings, QThread, pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import QApplication, QDialog, QLabel, QMessageBox  # noqa: E402

from ui import preferences, theme  # noqa: E402


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    folder = str(tmp_path_factory.mktemp("qsettings"))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, folder)
    application = QApplication.instance() or QApplication([])
    theme.apply_theme(application, "dark", persist=False)
    return application


def pump(app, ms=100):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def wait_until(app, condition, timeout=5.0):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return condition()


@pytest.fixture(autouse=True)
def no_modal_boxes(monkeypatch):
    """A QMessageBox would block the test; answer them instead."""
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))


# ------------------------------------------------------------------ auth screens
def test_login_rejects_a_wrong_password_and_accepts_the_right_one(app, db):
    from ui.login_screen import LoginScreen
    screen = LoginScreen(db=db)
    seen = []
    screen.login_success.connect(seen.append)
    screen.employee_button.click()
    screen.username_input.setText("marwan")
    screen.password_input.setText("wrong")
    screen.login_button.click()
    assert screen.error_label.isVisible() or screen.error_label.text()
    assert seen == []
    screen.password_input.setText("1234")
    screen.login_button.click()
    assert seen == ["employee"] and screen.logged_in_user["username"] == "marwan"


def test_signup_validates_and_stores_a_pending_request(app, db):
    from ui.signup_screen import SignupScreen
    screen = SignupScreen(db=db)
    done = []
    screen.signup_done.connect(lambda: done.append(True))
    screen.submit_button.click()                                    # everything empty
    assert done == [] and screen.error_label.text()
    screen.full_name_input.setText("New Person")
    screen.username_input.setText("newperson")
    screen.password_input.setText("abcd")
    screen.confirm_input.setText("abcd")
    screen.submit_button.click()
    assert db.get_user_status("newperson", "employee") == "pending"


# ------------------------------------------------------------------ chat screen with fakes
class FakeWorker(QThread):
    """A model worker that "writes" two pieces and finishes (stand-in for GenerateWorker)."""

    piece = pyqtSignal(str)
    done = pyqtSignal(bool)
    failed = pyqtSignal(str)

    def __init__(self, messages, parent=None):
        super().__init__(parent)
        self.messages = messages

    def stop(self):
        pass

    def run(self):
        self.piece.emit("Hello ")
        self.piece.emit("**world**")
        self.done.emit(False)


class FakeModelService:
    """The ModelService interface, backed by nothing."""

    def __init__(self):
        self.workers = []

    def is_loaded(self):
        return True

    def device(self):
        return "cuda"

    def create_load_worker(self, parent=None):
        raise AssertionError("the model is 'already loaded'; nothing should load it")

    def create_generate_worker(self, messages, parent=None):
        worker = FakeWorker(messages, parent)
        self.workers.append(worker)
        return worker

    def unload_if_idle(self, seconds=None):
        return False


def test_the_chat_screen_runs_on_an_injected_model_service(app, db, marwan, monkeypatch):
    from chat.backend_local import LocalBackend
    from chat.chat_client import ChatClient
    from ui.ai_chat_screen import AIChatScreen
    from ui.chat_bubble import ChatBubble

    backend = LocalBackend(db, marwan["id"])
    backend._model_present = lambda: True
    monkeypatch.setattr(preferences, "model_enabled", lambda: True)
    service = FakeModelService()
    screen = AIChatScreen(user=marwan, db=db, client=ChatClient(db, marwan["id"], backend=backend), model_service=service)
    screen.show()
    screen.refresh()
    screen.input.setPlainText("How do I build a CNN model?")
    screen._on_send()
    assert wait_until(app, lambda: not screen._generating)
    assert len(service.workers) == 1 and service.workers[0].messages[-1]["content"] == "How do I build a CNN model?"
    last = screen.findChildren(ChatBubble)[-1]
    assert last.text() == "Hello **world**"                        # raw text is what is stored
    labels = [l.text() for l in last.findChildren(QLabel) if l.objectName() == "ChatText"]
    assert "<b>world</b>" in labels[0]                             # ...and what is shown is formatted
    assert db.get_ai_messages(screen.current_chat_id)[-1]["source"] == "llm"


def test_a_data_question_never_starts_a_model_worker(app, db, marwan, monkeypatch):
    from ui.ai_chat_screen import AIChatScreen
    monkeypatch.setattr(preferences, "model_enabled", lambda: True)
    service = FakeModelService()
    screen = AIChatScreen(user=marwan, db=db, model_service=service)
    screen.refresh()
    screen.input.setPlainText("What tasks do I have?")
    screen._on_send()
    assert wait_until(app, lambda: not screen._generating)
    assert service.workers == []


# ------------------------------------------------------------------ settings + knowledge screens
def test_the_settings_switch_is_saved(app, db, marwan):
    from ui.settings_screen import SettingsScreen
    screen = SettingsScreen(user=marwan, db=db)
    assert preferences.use_ai_model() is True
    screen.ai_model_check.setChecked(False)
    assert preferences.use_ai_model() is False
    assert "off" in screen.ai_status_label.text()
    screen.ai_model_check.setChecked(True)
    assert preferences.use_ai_model() is True


def test_the_knowledge_screen_adds_and_removes_documents(app, db, manager, tmp_path):
    from knowledge.store import KnowledgeBase
    from ui.knowledge_screen import KnowledgeScreen
    note = tmp_path / "notes.md"
    note.write_text("# Notes\n\nGradient descent updates the weights.", encoding="utf-8")
    bad = tmp_path / "slides.pdf"
    bad.write_bytes(b"%PDF")
    screen = KnowledgeScreen(user=manager, db=db, kb=KnowledgeBase(db))
    assert screen.empty_label.isVisible() or not screen.table.isVisible()
    screen.add_files([str(note), str(bad)])
    assert screen.table.rowCount() == 1 and screen.table.item(0, 0).text() == "notes.md"
    assert "only .txt and .md" in screen.status.text()
    screen.table.cellWidget(0, 5).button.click()
    assert screen.table.rowCount() == 0


# ------------------------------------------------------------------ manager session detail
def test_the_session_detail_dialog_shows_numbers_and_events(app, db, manager, marwan, monkeypatch):
    from ui.manager_screen import ManagerScreen
    session_id = db.create_session(marwan["id"])
    db.log_event(session_id, "focus")
    db.log_event(session_id, "distraction")
    db.end_session(session_id, focus_seconds=125, away_seconds=5, distraction_seconds=60)
    screen = ManagerScreen(user=manager, db=db)
    captured = {}

    def fake_exec(dialog):
        captured["texts"] = [l.text() for l in dialog.findChildren(QLabel)]
        from PyQt5.QtWidgets import QTableWidget
        captured["rows"] = [dialog.findChildren(QTableWidget)[0].item(r, 1).text()
                            for r in range(dialog.findChildren(QTableWidget)[0].rowCount())]
        return 0

    monkeypatch.setattr(QDialog, "exec_", fake_exec)
    screen.sessions_page._open_session_detail(session_id)
    summary = next(t for t in captured["texts"] if t.startswith("Date:"))
    from ui.manager_screen import _fmt_hms
    assert "Marwan Hatem" in summary
    assert "Focus:" in summary and _fmt_hms(125) in summary and _fmt_hms(60) in summary and _fmt_hms(5) in summary
    assert captured["rows"] == ["focus", "distraction"]


def test_the_session_detail_dialog_handles_a_missing_session(app, db, manager, monkeypatch):
    from ui.manager_screen import ManagerScreen
    screen = ManagerScreen(user=manager, db=db)
    captured = {}
    monkeypatch.setattr(QDialog, "exec_", lambda dialog: captured.setdefault("texts", [l.text() for l in dialog.findChildren(QLabel)]) and 0)
    screen.sessions_page._open_session_detail(99999)
    assert "Session not found." in captured["texts"]
