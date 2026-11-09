"""Phase 7 desktop side: the Messages page (both roles), live events, polling, and the socket helpers."""
import base64
import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, Qt  # noqa: E402
from PyQt5.QtGui import QKeyEvent  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from ui.messages_screen import MAX_CHARS, MessagesScreen, state_text  # noqa: E402

BOSS, ANNA, BEN = "u-boss", "u-anna", "u-ben"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def msg(mid, sender, employee=ANNA, body=None, **extra):
    names = {BOSS: "Sara Boss", ANNA: "Anna Hamdan", BEN: "Ben Okafor"}
    return {"id": mid, "employee_id": employee, "sender_id": sender, "sender_name": names[sender],
            "body": body or f"message {mid}", "created_at": "2026-11-09T09:00:00+00:00", "delivered_at": None,
            "read_at": None, **extra}


class FakeDb:
    api = object()

    def __init__(self, history=None, conversations=None):
        self.history = history if history is not None else {ANNA: [msg(1, ANNA), msg(2, BOSS)]}
        self.conversations = conversations
        self.calls = []
        self.fail = None
        self.next_id = 100

    def get_chat_conversations(self):
        return self.conversations or []

    def get_chat_messages(self, employee_id, before_id=None, after_id=None, limit=50):
        self.calls.append(("page", employee_id, before_id, after_id))
        rows = self.history.get(employee_id, [])
        if after_id is not None:
            rows = [m for m in rows if m["id"] > after_id]
            return {"messages": rows[:limit], "has_more": len(rows) > limit}
        if before_id is not None:
            rows = [m for m in rows if m["id"] < before_id]
        return {"messages": rows[-limit:], "has_more": len(rows) > limit}

    def send_chat_message(self, employee_id, body):
        self.calls.append(("send", employee_id, body))
        if self.fail:
            return False, self.fail
        self.next_id += 1
        return True, msg(self.next_id, self.me, employee_id, body)

    def mark_chat_read(self, employee_id, up_to_id):
        self.calls.append(("read", employee_id, up_to_id))
        return True

    def count_unread_chat(self):
        return 3


def screen_for(qapp, role, db):
    db.me = BOSS if role == "manager" else ANNA
    page = MessagesScreen(user={"id": db.me, "full_name": "Me", "role": role}, db=db, start_socket=False)
    page.resize(1000, 700)
    page.show()
    page.refresh()
    qapp.processEvents()
    return page


def texts(view):
    return [(b.mine, b.text.text(), b.meta.text().split(" · ")[-1]) for _i, b in sorted(view.bubbles.items())]


# ---------------------------------------------------------------- employee
def test_employee_sees_one_conversation_and_marks_it_read(qapp):
    db = FakeDb()
    page = screen_for(qapp, "employee", db)
    assert page.conversation_list.isHidden()
    assert texts(page.chat)[0][:2] == (True, "message 1") and texts(page.chat)[1][:2] == (False, "message 2")
    assert ("read", ANNA, 2) in db.calls                            # the manager's message is now read
    theirs = page.chat.bubbles[2]
    assert theirs.layout().itemAt(0).widget().text() == "Sara Boss"  # the manager's name, from the server


def test_sending_with_enter_and_keeping_text_on_failure(qapp):
    db = FakeDb()
    page = screen_for(qapp, "employee", db)
    page.chat.input.setPlainText("  Can we talk today?  ")
    QApplication.sendEvent(page.chat.input, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    assert ("send", ANNA, "Can we talk today?") in db.calls and page.chat.input.toPlainText() == ""
    assert texts(page.chat)[-1] == (True, "Can we talk today?", "Sent")
    QApplication.sendEvent(page.chat.input, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.ShiftModifier))
    assert sum(c[0] == "send" for c in db.calls) == 1                # Shift+Enter is a new line, not send
    db.fail = "You are sending messages too fast. Wait a moment."
    page.chat.input.setPlainText("again")
    page.chat.send()
    assert page.chat.status.text() == db.fail and page.chat.input.toPlainText() == "again"
    page.chat.input.setPlainText("x" * (MAX_CHARS + 1))
    page.chat.send()
    assert "at most" in page.chat.status.text() and sum(c[0] == "send" for c in db.calls) == 2


def test_live_events_update_the_chat(qapp):
    db = FakeDb()
    page = screen_for(qapp, "employee", db)
    page.on_event({"type": "message", "message": msg(3, BOSS, body="Yes, at 3?")})
    assert texts(page.chat)[-1][:2] == (False, "Yes, at 3?") and ("read", ANNA, 3) in db.calls
    page.on_event({"type": "message", "message": msg(3, BOSS, body="Yes, at 3?")})   # a repeat is ignored
    assert len(page.chat.bubbles) == 3
    page.on_event({"type": "delivered", "message_ids": [1], "at": "2026-11-09T09:01:00+00:00"})
    assert texts(page.chat)[0][2] == "Delivered"
    page.on_event({"type": "read", "message_ids": [1], "at": "2026-11-09T09:02:00+00:00"})
    assert texts(page.chat)[0][2] == "Read"
    page.on_event({"type": "typing", "employee_id": ANNA, "user_id": BOSS})
    assert page.chat.typing_label.text() == "Sara Boss is typing…"
    page.on_event({"type": "message", "message": msg(9, BEN, employee=BEN)})   # not this conversation
    assert 9 not in page.chat.bubbles


def test_load_earlier_and_catch_up(qapp):
    history = {ANNA: [msg(i, ANNA if i % 2 else BOSS) for i in range(1, 61)]}
    db = FakeDb(history=history)
    page = screen_for(qapp, "employee", db)
    assert min(page.chat.bubbles) == 11 and page.chat.earlier_button.isVisible()
    page.chat.load_earlier()
    assert min(page.chat.bubbles) == 1 and not page.chat.earlier_button.isVisible()
    assert [b.message["id"] for b in (page.chat.rows.itemAt(i).layout().itemAt(0).widget() or
                                      page.chat.rows.itemAt(i).layout().itemAt(1).widget()
                                      for i in range(3))][:1] in ([1], [None])
    history[ANNA].append(msg(61, BOSS))
    page._poll()                                                     # polling fallback while the socket is down
    assert 61 in page.chat.bubbles


def test_user_text_is_plain(qapp):
    db = FakeDb(history={ANNA: [msg(1, BOSS, body="<b>not bold</b> & <a href='x'>link</a>")]})
    page = screen_for(qapp, "employee", db)
    label = page.chat.bubbles[1].text
    assert label.textFormat() == Qt.PlainText and label.text().startswith("<b>")


# ---------------------------------------------------------------- manager
def conversations():
    return [{"employee_id": ANNA, "employee_name": "Anna Hamdan", "employee_status": "active", "unread": 2,
             "last_message": msg(2, ANNA)},
            {"employee_id": BEN, "employee_name": "Ben Okafor", "employee_status": "disabled", "unread": 0,
             "last_message": msg(5, BEN, employee=BEN, body="bye")}]


def test_manager_list_unread_and_switching(qapp):
    db = FakeDb(history={ANNA: [msg(1, BOSS), msg(2, ANNA)], BEN: [msg(5, BEN, employee=BEN, body="bye")]},
                conversations=conversations())
    page = screen_for(qapp, "manager", db)
    assert not page.conversation_list.isHidden() and page.conversation_list.count() == 2
    assert page.chat.employee_id == ANNA and ("read", ANNA, 2) in db.calls
    assert "(2 new)" not in page.conversation_list.item(0).text()     # opened: no longer new
    page.on_event({"type": "message", "message": msg(6, BEN, employee=BEN, body="one more thing")})
    assert "(1 new)" in page.conversation_list.item(1).text() and "one more thing" in page.conversation_list.item(1).text()
    page.conversation_list.setCurrentRow(1)
    assert page.chat.employee_id == BEN and page.chat.title.text() == "Ben Okafor"
    assert not page.chat.input.isEnabled()                            # a disabled account cannot be written to


def test_unread_badge_signal(qapp):
    db = FakeDb()
    page = screen_for(qapp, "employee", db)
    seen = []
    page.unread_changed.connect(seen.append)
    page.refresh_unread()
    assert seen == [3]


def test_offline_database_explains(qapp):
    class LocalDb:
        pass

    page = MessagesScreen(user={"id": 1, "role": "employee"}, db=LocalDb(), start_socket=False)
    page.refresh()
    assert "online server" in page.notice.text() and not page.chat.input.isEnabled()


def test_state_text():
    assert state_text({}) == "Sent"
    assert state_text({"delivered_at": "x"}) == "Delivered"
    assert state_text({"delivered_at": "x", "read_at": "y"}) == "Read"


# ---------------------------------------------------------------- the socket helpers
def _jwt(exp):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"h.{payload}.s"


def test_socket_url_and_token_freshness():
    from cloud.api import ApiClient, _expires_in
    from cloud.credentials import MemoryCredentialStore

    assert ApiClient("https://api.example.com", credentials=MemoryCredentialStore()).socket_url("/chat/ws") == \
        "wss://api.example.com/chat/ws"
    assert ApiClient("http://localhost:8766/", credentials=MemoryCredentialStore()).socket_url("/chat/ws") == \
        "ws://localhost:8766/chat/ws"
    assert 590 < _expires_in(_jwt(time.time() + 600)) <= 600
    assert _expires_in("garbage") == 0.0

    api = ApiClient("http://x", credentials=MemoryCredentialStore())
    api._refresh_token, api._access_token = "r", _jwt(time.time() + 600)
    refreshed = []
    api._refresh = lambda: refreshed.append(1)
    assert api.socket_token() == api._access_token and refreshed == []     # still fresh: reused
    api._access_token = _jwt(time.time() + 30)
    api.socket_token()
    assert refreshed == [1]                                                 # about to expire: refreshed
    api.socket_token(force=True)
    assert refreshed == [1, 1]


def test_switching_conversations_leaves_nothing_behind(qapp):
    db = FakeDb(history={ANNA: [msg(1, ANNA, body="Anna's words")], BEN: [msg(5, BEN, employee=BEN, body="Ben's words")]},
                conversations=conversations())
    page = screen_for(qapp, "manager", db)
    page.conversation_list.setCurrentRow(1)
    qapp.processEvents()
    from PyQt5.QtWidgets import QLabel
    shown = [label.text() for label in page.chat.scroll.widget().findChildren(QLabel)
             if label.objectName() == "ChatText" and label.parent() is not None and not label.parent().isHidden()]
    assert "Anna's words" not in shown and "Ben's words" in shown
