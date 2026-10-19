"""The admin panel flows whose SQL moved into DatabaseManager methods (offscreen Qt)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt5")

from PyQt5.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from ui import theme  # noqa: E402


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    theme.apply_theme(application, "dark", persist=False)
    return application


@pytest.fixture(autouse=True)
def no_modal_boxes(monkeypatch):
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))


# ------------------------------------------------------------------ database methods
def test_username_taken_ignores_the_excluded_user(db, marwan):
    assert db.username_taken("marwan")
    assert not db.username_taken("marwan", except_user_id=marwan["id"])
    assert not db.username_taken("nobody")


def test_create_user_inserts_and_refuses_duplicates(db):
    import sqlite3
    user_id = db.create_user("lina", "pw12", "employee", "Lina K", status="pending")
    assert db.get_user_by_id(user_id)["status"] == "pending"
    with pytest.raises(sqlite3.IntegrityError):
        db.create_user("lina", "pw12", "employee", "Lina Again")


def test_count_user_related_rows_matches_what_the_cascade_removes(db, marwan, manager, add_session):
    add_session(marwan["id"], focus=60)
    sid = db.conn.execute("SELECT id FROM sessions").fetchone()["id"]
    db.log_event(sid, "focus")
    db.add_task(marwan["id"], "mine")
    db.add_task(manager["id"], "assigned to someone", assigned_by=marwan["id"])
    chat = db.create_ai_chat(marwan["id"], "c")
    db.add_ai_message(chat, "user", "hi")
    counts = db.count_user_related_rows(marwan["id"])
    assert counts == {"sessions": 1, "events": 1, "tasks": 2, "calendar": 0, "chats": 1}
    removed = db.delete_user_cascade(marwan["id"])
    assert removed["sessions"] == 1 and removed["events"] == 1 and removed["ai_chats"] == 1


def test_delete_all_tasks_returns_the_count(db, marwan):
    db.add_task(marwan["id"], "a")
    db.add_task(marwan["id"], "b")
    assert db.delete_all_tasks() == 2 and db.get_all_tasks() == []


def test_get_session_includes_the_owner_name(db, marwan):
    session_id = db.create_session(marwan["id"])
    row = db.get_session(session_id)
    assert row["full_name"] == "Marwan Hatem" and row["id"] == session_id
    assert db.get_session(99999) is None


# ------------------------------------------------------------------ dialogs and tabs
def test_add_user_dialog_creates_an_account_and_blocks_duplicates(app, db):
    from admin_ui.add_user_dialog import AddUserDialog
    dialog = AddUserDialog(db)
    dialog.username_input.setText("newuser")
    dialog.password_input.setText("pw12")
    dialog.full_name_input.setText("New User")
    dialog._on_submit()
    assert dialog.created_id is not None and db.get_user_by_id(dialog.created_id)["username"] == "newuser"

    again = AddUserDialog(db)
    again.username_input.setText("newuser")
    again.password_input.setText("pw12")
    again.full_name_input.setText("Other Person")
    again._on_submit()
    assert again.created_id is None                         # "Username taken"


def test_edit_user_dialog_cannot_take_another_accounts_username(app, db, marwan):
    from admin_ui.add_user_dialog import EditUserDialog
    dialog = EditUserDialog(db, db.get_user_by_id(marwan["id"]))
    dialog.username_input.setText("manager")
    dialog._on_submit()
    assert db.get_user_by_id(marwan["id"])["username"] == "marwan"


def test_users_tab_counts_dependent_rows_before_deleting(app, db, marwan, add_session):
    from admin_ui.users_tab import UsersTab
    add_session(marwan["id"], focus=10)
    tab = UsersTab(db)
    assert tab._related_counts(marwan["id"])["sessions"] == 1


def test_danger_tab_deletes_all_tasks_after_the_typed_confirmation(app, db, marwan, monkeypatch):
    from admin_ui.danger_tab import DangerTab
    db.add_task(marwan["id"], "to be deleted")
    tab = DangerTab(db)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("DELETE TASKS", True)))
    tab._delete_tasks()
    assert db.get_all_tasks() == []


def test_the_admin_window_builds_and_shows_the_counts(app, db):
    from admin_ui.admin_window import AdminWindow
    window = AdminWindow(db)
    window.show()
    window._update_counts()
    window.close()
