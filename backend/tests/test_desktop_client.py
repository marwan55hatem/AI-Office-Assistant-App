"""The desktop app's RemoteDatabase against the real API (Phase 2 acceptance).

The desktop client code is imported from the project root and talks to the API in
process (FastAPI's TestClient is an httpx client), on the real PostgreSQL test database.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cloud.api import ApiClient  # noqa: E402
from cloud.credentials import MemoryCredentialStore  # noqa: E402
from cloud.remote_db import RemoteDatabase  # noqa: E402
from tests.conftest import PASSWORD, auth, register  # noqa: E402


@pytest.fixture
def connect(client, tmp_path):
    opened = []

    def _connect(email, password=PASSWORD):
        api = ApiClient(str(client.base_url), http=client, credentials=MemoryCredentialStore())
        db = RemoteDatabase(api, outbox_path=str(tmp_path / f"outbox-{len(opened)}.db"), start_sync=False)
        opened.append(db)
        user, message = db.sign_in(email, password)
        assert user is not None, message
        return db, user

    yield _connect
    for db in opened:
        db.outbox.close()


def test_employee_and_manager_flows(client, connect):
    manager_tokens = register(client, company="Corp", email="boss@corp-test.com", name="Boss")
    code = client.get("/company", headers=auth(manager_tokens)).json()["join_code"]

    # an employee joins with the company code through the desktop client and waits
    boss, boss_user = connect("boss@corp-test.com")
    joiner = RemoteDatabase(ApiClient(str(client.base_url), http=client, credentials=MemoryCredentialStore()),
                            outbox_path=str(Path(boss.outbox._db.execute("PRAGMA database_list").fetchone()[2]).with_name("join.db")),
                            start_sync=False)
    assert joiner.join("Wendy", "wendy@corp-test.com", PASSWORD, company_code=code.lower())[0]
    assert joiner.sign_in("wendy@corp-test.com", PASSWORD)[0] is None          # not approved yet
    pending = boss.get_pending_users()
    assert [u["full_name"] for u in pending] == ["Wendy"]
    boss.approve_user(pending[0]["id"])
    joiner.outbox.close()

    wendy, wendy_user = connect("wendy@corp-test.com")
    assert wendy_user["role"] == "employee" and boss_user["role"] == "manager"

    # a work session recorded through the outbox
    session_id = wendy.create_session(wendy_user["id"])
    wendy.log_event(session_id, "focus")
    wendy.update_session_progress(session_id, 30, 0)
    wendy.log_event(session_id, "distraction")
    wendy.end_session(session_id, 50, 4, distraction_seconds=10, screen_productive=40)
    assert wendy.outbox.flush(wendy.api)

    today = wendy.get_today_sessions(wendy_user["id"])
    assert len(today) == 1 and today[0]["focus_seconds"] == 50 and today[0]["date"] == date.today().isoformat()
    assert [e["event_type"] for e in boss.get_session_events(session_id)] == ["focus", "distraction"]
    assert boss.get_today_totals() == {"focus_seconds": 50, "distraction_seconds": 10, "away_seconds": 4}
    status = {row["full_name"]: row["status"] for row in boss.get_employee_status_today()}
    assert status == {"Wendy": "present"}
    weekly = boss.get_weekly_report_all()
    assert weekly[0]["total_focus"] == 50 and weekly[0]["total_sessions"] == 1
    assert wendy.get_weekly_report(wendy_user["id"])["total_distraction"] == 10
    assert boss.get_sessions_history(days=7)[0]["full_name"] == "Wendy"
    assert boss.get_recent_events(5)[0]["full_name"] == "Wendy"

    # tasks: the manager assigns, the employee ticks it off
    task_id = boss.add_task(wendy_user["id"], "Quarterly report", "urgent", assigned_by=boss_user["id"],
                            deadline_date="2030-01-31", deadline_time="17:00")
    assigned = wendy.get_assigned_tasks(wendy_user["id"])
    assert [t["title"] for t in assigned] == ["Quarterly report"] and assigned[0]["deadline_time"] == "17:00"
    wendy.toggle_task(task_id)
    assert wendy.get_tasks(wendy_user["id"])[0]["is_done"] == 1
    own = wendy.add_task(wendy_user["id"], "Read the policy")
    assert {t["id"] for t in wendy.get_self_tasks(wendy_user["id"])} == {own}

    # calendar: invited employees see the event
    event_id = boss.create_calendar_event("Standup", date.today().isoformat(), boss_user["id"], start_time="09:30")
    assert boss.set_calendar_attendees(event_id, [wendy_user["id"]])[0]
    seen = wendy.get_today_events(wendy_user["id"])
    assert [(e["title"], e["start_time"], e["created_by_name"]) for e in seen] == [("Standup", "09:30", "Boss")]
    assert boss.update_calendar_event(event_id, title="Daily standup") == (True, "Event updated")
    assert boss.get_calendar_event(event_id)["attendees"][0]["full_name"] == "Wendy"

    # private AI chat history
    chat_id = wendy.create_ai_chat(wendy_user["id"], "Help")
    wendy.add_ai_message(chat_id, "user", "What tasks do I have?")
    wendy.add_ai_message(chat_id, "assistant", "One urgent task.", source="engine")
    assert [m["source"] for m in wendy.get_ai_messages(chat_id)] == [None, "engine"]
    assert wendy.chats.get_ai_chat(chat_id)["user_id"] == wendy_user["id"]       # the chat backend's owner check
    assert boss.get_ai_chat(chat_id) is None                                     # private, even from the manager

    # knowledge documents and visibility
    doc_id, created = boss.upsert_knowledge_doc("policy.md", "Holidays: 21 days", "everyone")
    boss.upsert_knowledge_doc("salaries.md", "secret", "managers")
    assert created and [d["filename"] for d in wendy.get_knowledge_docs(include_manager_only=False)] == ["policy.md"]
    assert wendy.knowledge_signature(False) != boss.knowledge_signature(True)

    # profile and password
    assert wendy.update_user_profile(wendy_user["id"], full_name="Wendy W.")[0]
    assert wendy.change_password(wendy_user["id"], "wrong", "a new password!")[0] is False
    assert wendy.change_password(wendy_user["id"], PASSWORD, "a new password!") == (True, "Password updated")


def test_the_chat_engine_answers_from_the_server(client, connect):
    """The chat's data answers (tasks, team) come from the server through the same methods.

    The intent classifier runs in the desktop app and needs PyTorch, which the server does not install,
    so this check runs only where PyTorch is available."""
    pytest.importorskip("torch")
    from assistant.answers import AssistantEngine

    register(client, company="Corp", email="boss@corp-test.com", name="Boss")
    boss, boss_user = connect("boss@corp-test.com")
    boss.add_task(boss_user["id"], "Prepare the budget")
    engine = AssistantEngine(boss, boss_user["id"])
    reply = engine.ask("what tasks do I have?", {})
    assert reply.intent == "list_tasks" and "Prepare the budget" in reply.text
