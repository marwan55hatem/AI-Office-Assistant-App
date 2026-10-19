"""Shared fixtures: a throw-away database, users, sessions and a chat backend.

Nothing here needs Qt, a camera, a GPU or the language model; ``sentencepiece`` is
imported first only because the translation models need it before PyQt5 on Windows.
"""

import os
import sys
from datetime import date, timedelta

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.environ["OFFICE_LLM"] = "1"          # tests switch the model on/off per backend, never globally

try:
    import sentencepiece  # noqa: F401
except ImportError:                     # pragma: no cover
    pass

from chat.backend_local import LocalBackend  # noqa: E402
from database.db_manager import DatabaseManager  # noqa: E402


@pytest.fixture
def db(tmp_path):
    """A fresh database (with the two demo accounts) in a temporary folder."""
    database = DatabaseManager(str(tmp_path / "test.db"))
    yield database
    database.close()


@pytest.fixture
def manager(db):
    """The demo manager account (a dict)."""
    return db.get_user("manager", "1234", "manager")


@pytest.fixture
def marwan(db):
    """The demo employee account (a dict)."""
    return db.get_user("marwan", "1234", "employee")


@pytest.fixture
def make_employee(db):
    """``make_employee("sara", "Sara Ali")`` -> an approved employee (dict)."""
    def make(username, full_name):
        ok, message = db.create_signup_request(username, "1234", full_name)
        assert ok, message
        user_id = db.conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]
        db.approve_user(user_id)
        return db.get_user(username, "1234", "employee")
    return make


@pytest.fixture
def add_session(db):
    """``add_session(user_id, days_ago=0, focus=600, distraction=0, away=0, running=False)``."""
    def add(user_id, days_ago=0, focus=0, distraction=0, away=0, running=False):
        day = (date.today() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        db.conn.execute(
            "INSERT INTO sessions (user_id, date, start_time, end_time, focus_seconds,"
            " distraction_seconds, away_seconds) VALUES (?, ?, '09:00:00', ?, ?, ?, ?)",
            (user_id, day, None if running else "10:00:00", focus, distraction, away))
        db.conn.commit()
    return add


class Chatter:
    """Drive a :class:`LocalBackend` like the chat screen does: send, stream, save."""

    def __init__(self, db, user, model_present=True):
        self.backend = LocalBackend(db, user["id"])
        self.backend.llm_enabled = True
        self.backend._model_present = lambda: model_present
        self.chat_id = self.backend.new_chat().id

    def ask(self, text, answer=None):
        """Send ``text``; returns the reply stream.  The reply is stored like the UI does."""
        self.backend.send_message(self.chat_id, text)
        stream = self.backend.stream_reply(self.chat_id, delay=0)
        self.backend.save_reply(self.chat_id, answer if answer is not None else (stream.full_text or "(model reply)"),
                                stream.source)
        return stream


@pytest.fixture
def chatter(db):
    """``chatter(user, model_present=True)`` -> a :class:`Chatter` with its own new chat."""
    return lambda user, model_present=True: Chatter(db, user, model_present)
