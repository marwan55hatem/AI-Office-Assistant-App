"""The database layer on temporary databases: accounts, tasks, calendar, sessions, migration."""

import sqlite3
from datetime import datetime, timedelta

from database.db_manager import DatabaseManager


# ------------------------------------------------------------------ accounts
def test_demo_accounts_exist_and_can_log_in(db):
    assert db.get_user("manager", "1234", "manager")["full_name"] == "Admin Manager"
    assert db.get_user("marwan", "1234", "employee")["role"] == "employee"


def test_wrong_password_or_role_does_not_log_in(db):
    assert db.get_user("marwan", "nope", "employee") is None
    assert db.get_user("marwan", "1234", "manager") is None


def test_signup_is_pending_until_a_manager_approves(db):
    ok, _ = db.create_signup_request("newbie", "abcd", "New Person")
    assert ok
    assert db.get_user_status("newbie", "employee") == "pending"
    assert [u["username"] for u in db.get_pending_users()] == ["newbie"]
    user_id = db.get_pending_users()[0]["id"]
    db.approve_user(user_id)
    assert db.get_user_status("newbie", "employee") == "approved"
    assert db.get_pending_users() == []


def test_rejected_signup_leaves_the_pending_list_and_cannot_log_in(db):
    db.create_signup_request("nope", "abcd", "Nope")
    db.reject_user(db.get_pending_users()[0]["id"])
    assert db.get_pending_users() == []
    assert db.get_user_status("nope", "employee") == "rejected"


def test_duplicate_username_is_refused(db):
    ok, message = db.create_signup_request("marwan", "abcd", "Another Marwan")
    assert not ok and message


def test_password_must_have_four_characters(db, marwan):
    ok, _ = db.update_user_password(marwan["id"], "abc")
    assert not ok
    ok, _ = db.update_user_password(marwan["id"], "abcd")
    assert ok and db.get_user("marwan", "abcd", "employee") is not None


def test_profile_update_changes_only_the_given_fields(db, marwan):
    ok, _ = db.update_user_profile(marwan["id"], full_name="Marwan H.")
    assert ok
    row = db.get_user_by_id(marwan["id"])
    assert row["full_name"] == "Marwan H." and row["username"] == "marwan"


def test_profile_cannot_take_another_users_username(db, marwan):
    ok, _ = db.update_user_profile(marwan["id"], username="manager")
    assert not ok


# ------------------------------------------------------------------ tasks
def test_task_lifecycle(db, marwan, manager):
    task_id = db.add_task(marwan["id"], "Write report", assigned_by=manager["id"], description="Q3 numbers")
    own_id = db.add_task(marwan["id"], "Buy milk")
    assert [t["title"] for t in db.get_assigned_tasks(marwan["id"])] == ["Write report"]
    assert [t["title"] for t in db.get_self_tasks(marwan["id"])] == ["Buy milk"]
    assert db.get_assigned_tasks(marwan["id"])[0]["description"] == "Q3 numbers"
    db.toggle_task(task_id)
    assert next(t for t in db.get_tasks(marwan["id"]) if t["id"] == task_id)["is_done"]
    db.toggle_task(task_id)
    assert not next(t for t in db.get_tasks(marwan["id"]) if t["id"] == task_id)["is_done"]
    db.delete_task(own_id)
    assert [t["title"] for t in db.get_tasks(marwan["id"])] == ["Write report"]


def test_done_tasks_sort_after_open_ones(db, marwan):
    first = db.add_task(marwan["id"], "first")
    db.add_task(marwan["id"], "second")
    db.toggle_task(first)
    assert [t["title"] for t in db.get_tasks(marwan["id"])] == ["second", "first"]


def test_deadlines_overdue_soon_and_cleared(db, marwan):
    now = datetime.now()
    overdue = db.add_task(marwan["id"], "late", deadline_date=(now - timedelta(days=1)).strftime("%Y-%m-%d"), deadline_time="09:00")
    soon = db.add_task(marwan["id"], "soon", deadline_date=(now + timedelta(hours=3)).strftime("%Y-%m-%d"),
                       deadline_time=(now + timedelta(hours=3)).strftime("%H:%M"))
    db.add_task(marwan["id"], "far", deadline_date=(now + timedelta(days=10)).strftime("%Y-%m-%d"))
    db.add_task(marwan["id"], "none")
    titles = {t["title"] for t in db.get_upcoming_deadlines(marwan["id"], within_hours=24)}
    assert titles == {"late", "soon"}
    ok, _ = db.update_task_deadline(soon, None)
    assert ok
    assert {t["title"] for t in db.get_upcoming_deadlines(marwan["id"], within_hours=24)} == {"late"}
    assert overdue


# ------------------------------------------------------------------ calendar
def test_calendar_event_is_visible_to_creator_and_attendees_only(db, manager, marwan, make_employee):
    outsider = make_employee("outsider", "Out Sider")
    today = datetime.now().strftime("%Y-%m-%d")
    event_id = db.create_calendar_event("Planning", today, manager["id"], start_time="10:00", end_time="11:00")
    ok, _ = db.set_calendar_attendees(event_id, [marwan["id"]])
    assert ok
    assert [e["title"] for e in db.get_calendar_events_for_user(manager["id"])] == ["Planning"]
    assert [e["title"] for e in db.get_calendar_events_for_user(marwan["id"])] == ["Planning"]
    assert db.get_calendar_events_for_user(outsider["id"]) == []
    assert [a["id"] for a in db.get_calendar_attendees(event_id)] == [marwan["id"]]


def test_deleting_an_event_removes_its_attendees(db, manager, marwan):
    event_id = db.create_calendar_event("Temp", datetime.now().strftime("%Y-%m-%d"), manager["id"])
    db.set_calendar_attendees(event_id, [marwan["id"]])
    db.delete_calendar_event(event_id)
    assert db.get_calendar_event(event_id) is None
    assert db.conn.execute("SELECT COUNT(*) FROM calendar_attendees").fetchone()[0] == 0


# ------------------------------------------------------------------ sessions + events
def test_session_totals_reach_the_weekly_report(db, marwan):
    session_id = db.create_session(marwan["id"])
    db.end_session(session_id, focus_seconds=1800, away_seconds=300, distraction_seconds=600)
    report = db.get_weekly_report(marwan["id"])
    assert report["total_focus"] == 1800 and report["total_distraction"] == 600 and report["total_away"] == 300


def test_today_totals_sum_everybody(db, marwan, make_employee, add_session):
    sara = make_employee("sara", "Sara Ali")
    add_session(marwan["id"], focus=100, distraction=10, away=1)
    add_session(sara["id"], focus=200, distraction=20, away=2)
    totals = db.get_today_totals()
    assert (totals["focus_seconds"], totals["distraction_seconds"], totals["away_seconds"]) == (300, 30, 3)


def test_events_are_logged_per_session(db, marwan):
    session_id = db.create_session(marwan["id"])
    db.log_event(session_id, "focus")
    db.log_event(session_id, "distraction")
    assert db.get_last_event(session_id)["event_type"] == "distraction"
    assert [e["event_type"] for e in db.get_session_events(session_id)] == ["focus", "distraction"]


def test_absent_employees_are_those_without_recent_sessions(db, marwan, make_employee, add_session):
    sara = make_employee("sara", "Sara Ali")
    add_session(marwan["id"], days_ago=0, focus=60)
    add_session(sara["id"], days_ago=10, focus=60)
    names = {e["full_name"] for e in db.get_absent_employees(days=3)}
    assert "Sara Ali" in names and "Marwan Hatem" not in names


# ------------------------------------------------------------------ deleting and resetting
def test_deleting_a_user_removes_everything_that_belongs_to_them(db, make_employee, manager, add_session):
    sara = make_employee("sara", "Sara Ali")
    add_session(sara["id"], focus=60)
    db.add_task(sara["id"], "her task", assigned_by=manager["id"])
    chat_id = db.create_ai_chat(sara["id"], "hers")
    db.add_ai_message(chat_id, "user", "hello")
    db.delete_user_cascade(sara["id"])
    assert db.get_user_by_id(sara["id"]) is None
    for table in ("sessions", "tasks", "ai_chats"):
        assert db.conn.execute("SELECT COUNT(*) FROM %s WHERE user_id = ?" % table, (sara["id"],)).fetchone()[0] == 0
    assert db.count_ai_messages(chat_id) == 0


def test_factory_reset_keeps_only_the_demo_accounts(db, make_employee, manager):
    make_employee("sara", "Sara Ali")
    db.add_task(manager["id"], "x")
    db.upsert_knowledge_doc("notes.md", "text")
    assert db.factory_reset()
    assert {u["username"] for u in db.get_all_users()} == {"manager", "marwan"}
    assert db.get_knowledge_docs() == [] and db.get_tasks(manager["id"]) == []


def test_export_then_import_restores_the_data(db, marwan, tmp_path):
    db.add_task(marwan["id"], "kept")
    backup = str(tmp_path / "backup.db")
    db.export_database(backup)
    db.delete_task(db.get_tasks(marwan["id"])[0]["id"])
    assert db.get_tasks(marwan["id"]) == []
    db.import_database(backup)
    assert [t["title"] for t in db.get_tasks(marwan["id"])] == ["kept"]


# ------------------------------------------------------------------ migration
def test_an_old_database_is_migrated_without_losing_rows(tmp_path):
    """A database made before descriptions, deadlines, chat sources and statuses existed."""
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, role TEXT NOT NULL, full_name TEXT NOT NULL);
        CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            title TEXT NOT NULL, priority TEXT DEFAULT 'normal', is_done INTEGER DEFAULT 0,
            assigned_by INTEGER, created_at TEXT);
        INSERT INTO users (username, password, role, full_name) VALUES ('old', 'pw12', 'employee', 'Old Timer');
        INSERT INTO tasks (user_id, title) VALUES (1, 'ancient task');
    """)
    old.commit()
    old.close()
    migrated = DatabaseManager(path)
    try:
        task_columns = {r["name"] for r in migrated.conn.execute("PRAGMA table_info(tasks)")}
        assert {"description", "deadline_date", "deadline_time"} <= task_columns
        assert "status" in {r["name"] for r in migrated.conn.execute("PRAGMA table_info(users)")}
        assert "source" in {r["name"] for r in migrated.conn.execute("PRAGMA table_info(ai_messages)")}
        assert [t["title"] for t in migrated.get_tasks(1)] == ["ancient task"]
        assert migrated.get_user("old", "pw12", "employee")["status"] == "approved"      # old accounts keep working
    finally:
        migrated.close()


def test_table_counts_feeds_the_admin_status_bar(db):
    counts = db.table_counts()
    assert counts == {"users": 2, "sessions": 0, "events": 0, "tasks": 0}
