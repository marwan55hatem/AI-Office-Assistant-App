"""Phase 2 data endpoints: session sync, history, stats, tasks, calendar, chats, documents,
profile and password change."""
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text

from tests.conftest import PASSWORD, add_active_employee, auth, login, register

TODAY = date.today()


def _session(sid=None, **counters):
    return {"id": str(sid or uuid.uuid4()), "local_date": str(TODAY),
            "started_at": datetime.now(UTC).isoformat(), **counters}


def _event(session_id, kind="focus"):
    return {"id": str(uuid.uuid4()), "session_id": session_id, "event_type": kind,
            "occurred_at": datetime.now(UTC).isoformat()}


def _team(client):
    manager = register(client)
    employee, employee_id = add_active_employee(client, manager, "w@acme-corp.com", "Wendy")
    other, other_id = add_active_employee(client, manager, "v@acme-corp.com", "Victor")
    return manager, employee, employee_id, other, other_id


# ---------------------------------------------------------------- sessions
def test_sync_is_idempotent_and_counters_only_grow(client):
    _, employee, *_ = _team(client)
    session = _session(focus_seconds=60, away_seconds=5)
    event = _event(session["id"])
    batch = {"sessions": [session], "events": [event]}
    assert client.post("/sessions/sync", json=batch, headers=auth(employee)).json() == {"sessions": 1, "events": 1}
    again = client.post("/sessions/sync", json=batch, headers=auth(employee)).json()
    assert again == {"sessions": 1, "events": 0}                  # the event is not stored twice
    older = {**session, "focus_seconds": 10}                       # a late, older sample
    client.post("/sessions/sync", json={"sessions": [older]}, headers=auth(employee))
    stored = client.get("/sessions", headers=auth(employee)).json()
    assert len(stored) == 1 and stored[0]["focus_seconds"] == 60 and stored[0]["running"] is True
    ended = {**session, "focus_seconds": 90, "ended_at": datetime.now(UTC).isoformat()}
    client.post("/sessions/sync", json={"sessions": [ended]}, headers=auth(employee))
    stored = client.get("/sessions", headers=auth(employee)).json()[0]
    assert stored["focus_seconds"] == 90 and stored["running"] is False


def test_sync_cannot_touch_another_users_session(client):
    _, employee, _, other, _ = _team(client)
    session = _session(focus_seconds=60)
    client.post("/sessions/sync", json={"sessions": [session]}, headers=auth(employee))
    hijack = {**session, "focus_seconds": 9999, "ended_at": datetime.now(UTC).isoformat()}
    result = client.post("/sessions/sync", json={"sessions": [hijack], "events": [_event(session["id"], "away")]},
                         headers=auth(other)).json()
    assert result == {"sessions": 0, "events": 0}
    assert client.get("/sessions", headers=auth(employee)).json()[0]["focus_seconds"] == 60


def test_sync_rejects_bad_values(client):
    _, employee, *_ = _team(client)
    bad = [_session(focus_seconds=-1), {**_session(), "event_type": "x"}, {**_session(), "user_id": str(uuid.uuid4())}]
    for session in bad:
        assert client.post("/sessions/sync", json={"sessions": [session]}, headers=auth(employee)).status_code == 422


def test_crashed_session_stops_counting_as_running(client, owner_engine):
    manager, employee, *_ = _team(client)
    client.post("/sessions/sync", json={"sessions": [_session(focus_seconds=5)]}, headers=auth(employee))
    with owner_engine.begin() as connection:
        connection.execute(text("UPDATE sessions SET last_seen_at = now() - interval '10 minutes'"))
    today = client.get("/stats/today", params={"day": str(TODAY)}, headers=auth(manager)).json()
    assert today["running_sessions"] == 0


def test_history_permissions(client):
    manager, employee, employee_id, other, other_id = _team(client)
    client.post("/sessions/sync", json={"sessions": [_session(focus_seconds=1)]}, headers=auth(employee))
    client.post("/sessions/sync", json={"sessions": [_session(focus_seconds=2)]}, headers=auth(other))
    assert len(client.get("/sessions", headers=auth(manager)).json()) == 2
    assert len(client.get("/sessions", params={"user_id": employee_id}, headers=auth(manager)).json()) == 1
    assert client.get("/sessions", params={"user_id": other_id}, headers=auth(employee)).status_code == 404
    own = client.get("/sessions", headers=auth(employee)).json()
    assert [s["full_name"] for s in own] == ["Wendy"]
    session_id = client.get("/sessions", params={"user_id": other_id}, headers=auth(manager)).json()[0]["id"]
    assert client.get(f"/sessions/{session_id}", headers=auth(employee)).status_code == 404
    assert client.get(f"/sessions/{session_id}/events", headers=auth(manager)).status_code == 200


# ---------------------------------------------------------------- stats
def test_today_and_range_stats(client):
    manager, employee, employee_id, other, _ = _team(client)
    session = _session(focus_seconds=100, distraction_seconds=20, away_seconds=5)
    client.post("/sessions/sync", json={"sessions": [session], "events": [_event(session["id"], "distraction")]},
                headers=auth(employee))
    old = {**_session(focus_seconds=50), "local_date": str(TODAY - timedelta(days=10))}
    client.post("/sessions/sync", json={"sessions": [old]}, headers=auth(employee))
    today = client.get("/stats/today", params={"day": str(TODAY)}, headers=auth(manager)).json()
    assert today["totals"] == {"focus_seconds": 100, "distraction_seconds": 20, "away_seconds": 5}
    wendy = next(e for e in today["employees"] if e["full_name"] == "Wendy")
    assert wendy["running"] and wendy["last_event_type"] == "distraction" and wendy["sessions"] == 1
    victor = next(e for e in today["employees"] if e["full_name"] == "Victor")
    assert victor["sessions"] == 0 and not victor["running"]
    week = client.get("/stats/range", params={"start": str(TODAY - timedelta(days=6)), "end": str(TODAY)},
                      headers=auth(manager)).json()
    assert next(r for r in week if r["full_name"] == "Wendy")["total_focus"] == 100     # the old session is outside
    month = client.get("/stats/range", params={"start": str(TODAY - timedelta(days=29)), "end": str(TODAY)},
                       headers=auth(employee)).json()
    assert len(month) == 1 and month[0]["total_focus"] == 150                           # an employee sees only themselves
    assert client.get("/stats/today", params={"day": str(TODAY)}, headers=auth(employee)).status_code == 403
    assert client.get("/events/recent", headers=auth(employee)).status_code == 403
    assert client.get("/events/recent", headers=auth(manager)).json()[0]["full_name"] == "Wendy"


# ---------------------------------------------------------------- tasks
def test_task_rules(client):
    manager, employee, employee_id, other, other_id = _team(client)
    own = client.post("/tasks", json={"title": "my own"}, headers=auth(employee)).json()
    assert own["assigned_by"] is None
    assert client.post("/tasks", json={"title": "for victor", "user_id": other_id},
                       headers=auth(employee)).status_code == 404               # employees cannot assign
    assigned = client.post("/tasks", json={"title": "report", "user_id": employee_id, "priority": "urgent",
                                           "deadline_date": "2030-01-31", "deadline_time": "17:00"},
                           headers=auth(manager)).json()
    assert assigned["assigned_by"] is not None and assigned["deadline_time"] == "17:00:00"
    titles = {t["title"] for t in client.get("/tasks", headers=auth(employee)).json()}
    assert titles == {"my own", "report"}
    assert {t["title"] for t in client.get("/tasks", params={"kind": "assigned"}, headers=auth(employee)).json()} == {"report"}
    assert client.post(f"/tasks/{assigned['id']}/toggle", headers=auth(employee)).json()["is_done"] is True
    assert client.post(f"/tasks/{own['id']}/toggle", headers=auth(other)).status_code == 404
    assert client.delete(f"/tasks/{assigned['id']}", headers=auth(employee)).status_code == 404   # assigned: manager deletes
    assert client.delete(f"/tasks/{own['id']}", headers=auth(employee)).status_code == 204
    cleared = client.patch(f"/tasks/{assigned['id']}/deadline", json={"deadline_date": None}, headers=auth(manager)).json()
    assert cleared["deadline_date"] is None and cleared["deadline_time"] is None


# ---------------------------------------------------------------- calendar
def test_calendar_visibility_and_manager_only_writes(client):
    manager, employee, employee_id, other, other_id = _team(client)
    event = client.post("/calendar", json={"title": "Standup", "event_date": str(TODAY), "start_time": "09:00"},
                        headers=auth(manager)).json()
    assert client.post("/calendar", json={"title": "x", "event_date": str(TODAY)}, headers=auth(employee)).status_code == 403
    client.put(f"/calendar/{event['id']}/attendees", json={"user_ids": [employee_id]}, headers=auth(manager))
    assert [e["title"] for e in client.get("/calendar", headers=auth(employee)).json()] == ["Standup"]
    assert client.get("/calendar", headers=auth(other)).json() == []                 # not invited
    assert client.get(f"/calendar/{event['id']}", headers=auth(other)).status_code == 404
    detail = client.get(f"/calendar/{event['id']}", headers=auth(employee)).json()
    assert detail["attendee_count"] == 1 and detail["attendees"][0]["full_name"] == "Wendy"
    assert client.patch(f"/calendar/{event['id']}", json={"title": None}, headers=auth(manager)).status_code == 422
    assert client.patch(f"/calendar/{event['id']}", json={"title": "Daily"}, headers=auth(manager)).json()["title"] == "Daily"
    assert client.delete(f"/calendar/{event['id']}", headers=auth(manager)).status_code == 204
    assert client.get("/calendar", headers=auth(employee)).json() == []


# ---------------------------------------------------------------- AI chats
def test_chats_are_private_even_from_managers(client):
    manager, employee, *_ = _team(client)
    chat = client.post("/ai/chats", json={"title": "help"}, headers=auth(employee)).json()
    client.post(f"/ai/chats/{chat['id']}/messages", json={"role": "user", "content": "hello"}, headers=auth(employee))
    client.post(f"/ai/chats/{chat['id']}/messages", json={"role": "assistant", "content": "hi", "source": "engine"},
                headers=auth(employee))
    listed = client.get("/ai/chats", headers=auth(employee)).json()
    assert listed[0]["message_count"] == 2 and listed[0]["last_message"] == "hi"
    assert [m["content"] for m in client.get(f"/ai/chats/{chat['id']}/messages", params={"limit": 1},
                                             headers=auth(employee)).json()] == ["hi"]
    assert client.get(f"/ai/chats/{chat['id']}/messages", headers=auth(manager)).status_code == 404
    assert client.get("/ai/chats", headers=auth(manager)).json() == []
    assert client.post(f"/ai/chats/{chat['id']}/messages", json={"role": "system", "content": "x"},
                       headers=auth(employee)).status_code == 422


# ---------------------------------------------------------------- documents
def test_documents_visibility(client):
    manager, employee, *_ = _team(client)
    public = client.put("/documents", json={"filename": "Policy.md", "content": "Holidays: 21 days"},
                        headers=auth(manager)).json()
    secret = client.put("/documents", json={"filename": "salaries.md", "content": "secret", "visibility": "managers"},
                        headers=auth(manager)).json()
    assert public["created"] and public["words"] == 3
    replaced = client.put("/documents", json={"filename": "policy.md", "content": "Holidays: 25 days"},
                          headers=auth(manager)).json()
    assert replaced["created"] is False and replaced["id"] == public["id"]   # same name, any case
    assert [d["filename"] for d in client.get("/documents", headers=auth(employee)).json()] == ["Policy.md"]
    assert client.get(f"/documents/{secret['id']}", headers=auth(employee)).status_code == 404
    assert client.put("/documents", json={"filename": "x.md", "content": "x"}, headers=auth(employee)).status_code == 403
    client.patch(f"/documents/{secret['id']}", json={"visibility": "everyone"}, headers=auth(manager))
    assert len(client.get("/documents", headers=auth(employee)).json()) == 2


# ---------------------------------------------------------------- profile and password
def test_profile_and_password_change(client):
    manager, employee, *_ = _team(client)
    assert client.patch("/users/me", json={"full_name": "Wendy W."}, headers=auth(employee)).json()["full_name"] == "Wendy W."
    assert client.patch("/users/me", json={"email": "x@y.com"}, headers=auth(employee)).status_code == 422
    wrong = client.post("/auth/change-password", json={"current_password": "nope", "new_password": "a new password!"},
                        headers=auth(employee))
    assert wrong.status_code == 400
    fresh = client.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "a new password!"},
                        headers=auth(employee))
    assert fresh.status_code == 200
    # other devices are signed out; the new pair works; the old password does not
    assert client.post("/auth/refresh", json={"refresh_token": employee["refresh_token"]}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": fresh.json()["refresh_token"]}).status_code == 200
    assert login(client, "w@acme-corp.com").status_code == 401
    assert login(client, "w@acme-corp.com", "a new password!").status_code == 200


def test_manager_lists_employees_only_with_role_filter(client):
    manager, *_ = _team(client)
    names = [u["full_name"] for u in client.get("/users", params={"role": "employee"}, headers=auth(manager)).json()]
    assert names == ["Victor", "Wendy"]
