"""Phase 7: the manager-employee chat -- isolation, ordering, paging, read/delivered state,
limits, notifications, the unread e-mail, and the live WebSocket channel."""
import time

import pytest
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.services.email.providers import FakeProvider
from app.services.email.worker import process_due
from tests.conftest import add_active_employee, auth, register


@pytest.fixture
def team(client):
    boss = register(client, "Acme", "boss@acme-corp.com", "Sara Boss")
    anna, anna_id = add_active_employee(client, boss, "anna@acme-corp.com", "Anna Hamdan")
    ben, ben_id = add_active_employee(client, boss, "ben@acme-corp.com", "Ben Okafor")
    boss_id = client.get("/auth/me", headers=auth(boss)).json()["user"]["id"]
    return {"boss": boss, "anna": anna, "ben": ben, "anna_id": anna_id, "ben_id": ben_id, "boss_id": boss_id}


def say(client, tokens, employee_id, body):
    response = client.post(f"/chat/{employee_id}/messages", json={"body": body}, headers=auth(tokens))
    assert response.status_code == 201, response.text
    return response.json()


def page(client, tokens, employee_id, **params):
    response = client.get(f"/chat/{employee_id}/messages", params=params, headers=auth(tokens))
    assert response.status_code == 200, response.text
    return response.json()


def email_rows(owner_engine):
    with owner_engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(
            "SELECT e.*, u.email AS to_email FROM email_log e JOIN users u ON u.id = e.user_id "
            "WHERE e.template = 'chat_unread' ORDER BY e.id"))]


# ---------------------------------------------------------------- the conversation
def test_both_sides_write_and_read_in_order(client, team):
    a = team["anna_id"]
    first = say(client, team["anna"], a, "Hello, do you have a minute?")
    second = say(client, team["boss"], a, "Sure, what's up?")
    third = say(client, team["anna"], a, "About the report")
    for who in ("anna", "boss"):
        data = page(client, team[who], a)
        assert [m["id"] for m in data["messages"]] == [first["id"], second["id"], third["id"]]
        assert data["has_more"] is False
    assert second["sender_id"] == team["boss_id"] and second["employee_id"] == a
    assert [m["sender_name"] for m in page(client, team["anna"], a)["messages"]] ==         ["Anna Hamdan", "Sara Boss", "Anna Hamdan"]                    # the employee learns the manager's name


def test_paging_back_and_catching_up(client, team):
    a = team["anna_id"]
    ids = [say(client, team["anna"] if i % 2 else team["boss"], a, f"message {i}")["id"] for i in range(7)]
    latest = page(client, team["boss"], a, limit=3)
    assert [m["id"] for m in latest["messages"]] == ids[-3:] and latest["has_more"]
    older = page(client, team["boss"], a, limit=3, before_id=ids[-3])
    assert [m["id"] for m in older["messages"]] == ids[1:4] and older["has_more"]
    oldest = page(client, team["boss"], a, limit=3, before_id=ids[1])
    assert [m["id"] for m in oldest["messages"]] == ids[:1] and not oldest["has_more"]
    newer = page(client, team["boss"], a, after_id=ids[2], limit=2)
    assert [m["id"] for m in newer["messages"]] == ids[3:5] and newer["has_more"]
    assert page(client, team["boss"], a, after_id=ids[-1])["messages"] == []


def test_employees_cannot_see_each_others_chats(client, team):
    say(client, team["anna"], team["anna_id"], "private")
    assert client.get(f"/chat/{team['anna_id']}/messages", headers=auth(team["ben"])).status_code == 404
    assert client.post(f"/chat/{team['anna_id']}/messages", json={"body": "hi"},
                       headers=auth(team["ben"])).status_code == 404
    assert client.post(f"/chat/{team['anna_id']}/read", json={"up_to_id": 10**9},
                       headers=auth(team["ben"])).status_code == 404
    assert [c["employee_id"] for c in client.get("/chat/conversations", headers=auth(team["ben"])).json()] == \
        [team["ben_id"]]
    # a manager's id is not a conversation
    assert client.get(f"/chat/{team['boss_id']}/messages", headers=auth(team["boss"])).status_code == 404
    other = register(client, "Globex", "boss@globex-corp.com", "Gil")
    assert client.get(f"/chat/{team['anna_id']}/messages", headers=auth(other)).status_code == 404
    assert client.get("/chat/conversations", headers=auth(other)).json() == []
    assert client.get("/chat/unread-count", headers=auth(other)).json() == {"unread": 0}


def test_conversation_list_puts_news_first(client, team):
    say(client, team["ben"], team["ben_id"], "Ben here")
    say(client, team["anna"], team["anna_id"], "Anna one")
    say(client, team["anna"], team["anna_id"], "Anna two")
    convs = client.get("/chat/conversations", headers=auth(team["boss"])).json()
    assert [(c["employee_name"], c["unread"]) for c in convs] == [("Anna Hamdan", 2), ("Ben Okafor", 1)]
    assert convs[0]["last_message"]["body"] == "Anna two"
    # a newer conversation without unread messages comes after the unread ones
    say(client, team["boss"], team["ben_id"], "read: nothing new for the manager here")
    client.post(f"/chat/{team['ben_id']}/read", json={"up_to_id": 10**9}, headers=auth(team["boss"]))
    convs = client.get("/chat/conversations", headers=auth(team["boss"])).json()
    assert [(c["employee_name"], c["unread"]) for c in convs] == [("Anna Hamdan", 2), ("Ben Okafor", 0)]
    assert client.get("/chat/unread-count", headers=auth(team["boss"])).json() == {"unread": 2}   # Ben's was read


def test_read_and_delivered_state(client, team):
    a = team["anna_id"]
    m1 = say(client, team["anna"], a, "one")
    m2 = say(client, team["anna"], a, "two")
    assert m1["delivered_at"] is None and m1["read_at"] is None              # nobody was connected
    page(client, team["anna"], a)                                           # the sender's own fetch
    assert page(client, team["anna"], a)["messages"][0]["delivered_at"] is None
    page(client, team["boss"], a)                                           # the manager's device got them
    seen = page(client, team["anna"], a)["messages"]
    assert all(m["delivered_at"] for m in seen) and all(m["read_at"] is None for m in seen)

    assert client.post(f"/chat/{a}/read", json={"up_to_id": m1["id"]}, headers=auth(team["boss"])).json() == \
        {"read": 1}
    seen = page(client, team["anna"], a)["messages"]
    assert seen[0]["read_at"] and seen[1]["read_at"] is None
    assert client.get("/chat/unread-count", headers=auth(team["boss"])).json() == {"unread": 1}
    # reading your own messages changes nothing
    assert client.post(f"/chat/{a}/read", json={"up_to_id": m2["id"]}, headers=auth(team["anna"])).json() == \
        {"read": 0}
    reply = say(client, team["boss"], a, "Got it")
    assert client.get("/chat/unread-count", headers=auth(team["anna"])).json() == {"unread": 1}
    assert client.post(f"/chat/{a}/read", json={"up_to_id": reply["id"]}, headers=auth(team["anna"])).json() == \
        {"read": 1}
    assert client.get("/chat/unread-count", headers=auth(team["anna"])).json() == {"unread": 0}


# ---------------------------------------------------------------- limits
def test_message_rules(client, team):
    a, h = team["anna_id"], auth(team["anna"])
    assert client.post(f"/chat/{a}/messages", json={"body": "   "}, headers=h).status_code == 422
    assert client.post(f"/chat/{a}/messages", json={"body": "x" * 4001}, headers=h).status_code == 422
    assert client.post(f"/chat/{a}/messages", json={"body": "x" * 4000}, headers=h).status_code == 201
    cleaned = client.post(f"/chat/{a}/messages", json={"body": "  hi\x00 there\r\nline two\x07  "}, headers=h).json()
    assert cleaned["body"] == "hi there\nline two"
    assert client.post(f"/chat/{a}/messages", json={"body": "x", "sender_id": team["boss_id"]},
                       headers=h).status_code == 422                       # nobody writes as someone else


def test_flood_limit(client, team):
    a = team["anna_id"]
    for i in range(8):
        say(client, team["anna"], a, f"m{i}")
    codes = [client.post(f"/chat/{a}/messages", json={"body": "again"}, headers=auth(team["anna"])).status_code
             for _ in range(4)]
    assert codes == [201, 201, 429, 429]
    assert say(client, team["boss"], a, "the manager is not slowed down by Anna")


def test_a_disabled_employee_cannot_be_written_to(client, team):
    say(client, team["anna"], team["anna_id"], "bye")
    client.patch(f"/users/{team['anna_id']}/status", json={"status": "disabled"}, headers=auth(team["boss"]))
    assert client.post(f"/chat/{team['anna_id']}/messages", json={"body": "hi"},
                       headers=auth(team["boss"])).status_code == 409
    convs = client.get("/chat/conversations", headers=auth(team["boss"])).json()
    assert [c["employee_status"] for c in convs if c["employee_id"] == team["anna_id"]] == ["disabled"]


# ---------------------------------------------------------------- notifications and e-mail
def test_one_notification_per_conversation(client, team):
    a = team["anna_id"]
    say(client, team["anna"], a, "first")
    last = say(client, team["anna"], a, "second, longer " + "x" * 200)
    notes = client.get("/notifications", headers=auth(team["boss"])).json()
    assert len(notes) == 1 and notes[0]["kind"] == "chat_message" and notes[0]["link"] == f"chat:{a}"
    assert notes[0]["title"] == "New message from Anna Hamdan" and notes[0]["body"].endswith("…")
    client.post(f"/chat/{a}/read", json={"up_to_id": last["id"]}, headers=auth(team["boss"]))
    assert client.get("/notifications/unread-count", headers=auth(team["boss"])).json() == {"unread": 0}


def make_due(owner_engine):
    with owner_engine.begin() as c:
        c.execute(text("UPDATE email_log SET next_attempt_at = now() - interval '1 second' WHERE status = 'queued'"))


def test_unread_messages_are_emailed_later_without_their_text(client, team, owner_engine):
    a = team["anna_id"]
    for body in ("secret plan A", "secret plan B", "secret plan C"):
        say(client, team["boss"], a, body)
    [row] = email_rows(owner_engine)                                    # one e-mail for the burst
    assert row["status"] == "queued" and row["to_email"] == "anna@acme-corp.com"
    minutes = get_settings().chat_email_delay_minutes
    assert (row["next_attempt_at"] - row["created_at"]).total_seconds() >= minutes * 60 - 5
    fake = FakeProvider()
    assert process_due(fake) == {}                                      # not yet
    make_due(owner_engine)
    assert process_due(fake) == {"sent": 1}
    mail = fake.sent[0]
    assert mail.subject == "New message from Sara Boss" and "/messages" in mail.text
    assert "secret" not in mail.text and "secret" not in mail.html
    say(client, team["boss"], a, "one more")                             # a new e-mail can be queued again
    assert len(email_rows(owner_engine)) == 2


def test_no_email_when_the_message_was_read_in_time(client, team, owner_engine):
    message = say(client, team["anna"], team["anna_id"], "quick question")
    client.post(f"/chat/{team['anna_id']}/read", json={"up_to_id": message["id"]}, headers=auth(team["boss"]))
    make_due(owner_engine)
    assert process_due(FakeProvider()) == {"skipped": 1}
    assert email_rows(owner_engine)[0]["error"] == "the message was read"


# ---------------------------------------------------------------- the live channel
def connect(client, tokens):
    socket = client.websocket_connect("/chat/ws")
    ws = socket.__enter__()
    ws.send_json({"type": "auth", "token": tokens["access_token"]})
    ready = ws.receive_json()
    assert ready["type"] == "ready"
    return socket, ws


def nothing_pending(ws):
    """The next thing on this socket is the answer to a ping: nothing else was pushed."""
    ws.send_json({"type": "ping"})
    return ws.receive_json() == {"type": "pong"}


def test_live_delivery_read_receipts_and_typing(client, team, owner_engine):
    a = team["anna_id"]
    boss_socket, boss_ws = connect(client, team["boss"])
    ben_socket, ben_ws = connect(client, team["ben"])
    anna_socket, anna_ws = connect(client, team["anna"])
    try:
        sent = say(client, team["anna"], a, "Are you there?")
        assert sent["delivered_at"] is not None                          # a manager was connected
        pushed = boss_ws.receive_json()
        assert pushed["type"] == "message" and pushed["message"]["body"] == "Are you there?"
        assert anna_ws.receive_json()["message"]["id"] == sent["id"]     # the sender's other devices too
        assert nothing_pending(ben_ws)                                   # another employee hears nothing

        client.post(f"/chat/{a}/read", json={"up_to_id": sent["id"]}, headers=auth(team["boss"]))
        receipt = anna_ws.receive_json()
        assert receipt["type"] == "read" and receipt["message_ids"] == [sent["id"]]
        assert receipt["reader_id"] == team["boss_id"]
        assert boss_ws.receive_json()["type"] == "read"

        boss_ws.send_json({"type": "typing", "employee_id": a})
        typing = anna_ws.receive_json()
        assert typing == {"type": "typing", "employee_id": a, "user_id": team["boss_id"]}
        ben_ws.send_json({"type": "typing", "employee_id": a})          # not Ben's conversation: dropped
        assert nothing_pending(anna_ws) and nothing_pending(boss_ws)
        assert email_rows(owner_engine) == []                           # online: no e-mail queued
    finally:
        for socket in (boss_socket, ben_socket, anna_socket):
            socket.__exit__(None, None, None)


def test_bad_or_missing_token_closes_the_socket(client, team, monkeypatch):
    with client.websocket_connect("/chat/ws") as ws:
        ws.send_json({"type": "auth", "token": "not-a-token"})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4003
    with client.websocket_connect("/chat/ws") as ws:
        ws.send_json({"type": "auth", "token": team["boss"]["refresh_token"]})   # wrong kind of token
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4003
    from app.routers import chat
    monkeypatch.setattr(chat, "AUTH_SECONDS", 0.3)
    with client.websocket_connect("/chat/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4003


def test_the_socket_closes_when_the_token_expires(client, team, monkeypatch):
    from app.core.security import create_access_token
    settings = get_settings()
    monkeypatch.setattr(settings, "access_token_minutes", 0.04)          # about two seconds
    company_id = client.get("/auth/me", headers=auth(team["boss"])).json()["company"]["id"]
    short = create_access_token(team["boss_id"], company_id, "manager")
    with client.websocket_connect("/chat/ws") as ws:
        ws.send_json({"type": "auth", "token": short})
        assert ws.receive_json()["type"] == "ready"
        started = time.monotonic()
        assert ws.receive_json() == {"type": "expired"}
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4001 and time.monotonic() - started < 10
