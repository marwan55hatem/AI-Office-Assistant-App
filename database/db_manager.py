"""SQLite persistence layer for the Desktop AI Office Assistant.

The whole application shares a single :class:`DatabaseManager` instance, which
owns one connection to ``data/office_assistant.db`` and exposes every query the
UI needs (users, sessions, events, tasks).

The connection is opened with ``check_same_thread=False`` so a future detection
thread can reuse it, and ``PRAGMA foreign_keys = ON`` so the relations between
users, sessions, events and tasks are actually enforced.

Run this module directly to exercise every method against a throwaway database::

    python database/db_manager.py
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    from database.repositories import REPOSITORIES
except ImportError:                     # run as a script: ``python database/db_manager.py``
    from repositories import REPOSITORIES

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from app_paths import USER_DATA_DIR as DATA_DIR      # %LOCALAPPDATA%\OfficeAssistant when installed
except ImportError:                                      # run as a script from database/
    DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "office_assistant.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    role        TEXT NOT NULL,
    full_name   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'approved'
);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    date            TEXT,
    start_time      TEXT,
    end_time        TEXT,
    focus_seconds   INTEGER DEFAULT 0,
    distraction_seconds INTEGER DEFAULT 0,
    away_seconds    INTEGER DEFAULT 0,
    distractions    INTEGER DEFAULT 0,
    screen_productive_seconds INTEGER DEFAULT 0,
    screen_distracted_seconds INTEGER DEFAULT 0,
    screen_idle_seconds       INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER,
    event_type  TEXT,
    timestamp   TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    assigned_by   INTEGER,
    title         TEXT NOT NULL,
    is_done       INTEGER DEFAULT 0,
    priority      TEXT DEFAULT 'normal',
    created_at    TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (assigned_by) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT,
    event_date   TEXT NOT NULL,
    start_time   TEXT,
    end_time     TEXT,
    created_by   INTEGER NOT NULL,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (created_by) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS calendar_attendees (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    UNIQUE(event_id, user_id),
    FOREIGN KEY (event_id) REFERENCES calendar_events (id)
        ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS ai_chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    title      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (chat_id) REFERENCES ai_chats (id) ON DELETE CASCADE
);

-- The manager's documents for the assistant (text / Markdown).  visibility is
-- 'everyone' or 'managers'; uploaded_by is informational (no foreign key: a document
-- stays when the person who added it is deleted).
CREATE TABLE IF NOT EXISTS knowledge_docs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL UNIQUE,
    content     TEXT NOT NULL,
    visibility  TEXT NOT NULL DEFAULT 'everyone',
    uploaded_by INTEGER,
    size        INTEGER NOT NULL DEFAULT 0,
    words       INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_chats_user
    ON ai_chats(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_messages_chat
    ON ai_messages(chat_id, id);
"""

#: Sentinel for "argument not passed" (so ``None`` can mean "clear this field").
_UNSET = object()


def deadline_due_datetime(deadline_date: Optional[str], deadline_time: Optional[str] = None):
    """Return the moment a task deadline falls due, or ``None`` if invalid.

    ``deadline_date`` is ``'YYYY-MM-DD'`` and ``deadline_time`` is ``'HH:MM'``.
    A deadline *without* a time means "end of that day": it is due at 23:59:59,
    so a task due "today" is not overdue until the day is over.
    """
    if not deadline_date:
        return None
    try:
        day = datetime.strptime(str(deadline_date)[:10], "%Y-%m-%d")
        if deadline_time:
            clock = datetime.strptime(str(deadline_time)[:5], "%H:%M")
            return day.replace(hour=clock.hour, minute=clock.minute)
        return day.replace(hour=23, minute=59, second=59)
    except ValueError:
        return None


class DatabaseManager:
    """Single entry point for every SQLite read/write in the application."""

    BASE_DIR = BASE_DIR
    DATA_DIR = DATA_DIR
    DB_PATH = DB_PATH

    # ------------------------------------------------------------------ #
    #  Setup
    # ------------------------------------------------------------------ #
    def __init__(self, db_path=DB_PATH):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

        # Narrow views of this database (db.users, db.chats, ...): same connection,
        # fewer methods each.  See database/repositories.py.
        for name, repository_class in REPOSITORIES.items():
            setattr(self, name, repository_class(self))

        self.create_tables()
        self.seed_demo_users()

    def create_tables(self) -> None:
        """Create the four application tables and migrate older databases."""
        self.conn.executescript(SCHEMA_SQL)

        # Migration: a database created before the signup workflow has a users
        # table without the ``status`` column.  Add it in place so existing rows
        # (the demo accounts) become 'approved' and keep working.
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(users)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "status" not in columns:
            cursor.execute(
                "ALTER TABLE users ADD COLUMN status TEXT NOT NULL"
                " DEFAULT 'approved'"
            )

        # Migration: screen-time columns added with the detection feature.
        cursor.execute("PRAGMA table_info(sessions)")
        session_columns = {row["name"] for row in cursor.fetchall()}
        for column in (
            "screen_productive_seconds",
            "screen_distracted_seconds",
            "screen_idle_seconds",
        ):
            if column not in session_columns:
                cursor.execute(
                    f"ALTER TABLE sessions ADD COLUMN {column} INTEGER DEFAULT 0"
                )

        # Migration: distraction became a *time* counter; older databases only
        # have the legacy ``distractions`` count column.
        if "distraction_seconds" not in session_columns:
            cursor.execute(
                "ALTER TABLE sessions ADD COLUMN distraction_seconds INTEGER DEFAULT 0"
            )

        # Migration: optional task description (NULL for every existing task).
        cursor.execute("PRAGMA table_info(tasks)")
        task_columns = {row["name"] for row in cursor.fetchall()}
        if "description" not in task_columns:
            cursor.execute(
                "ALTER TABLE tasks ADD COLUMN description TEXT DEFAULT NULL"
            )

        # Migration: optional task deadline (date + time, both NULL for every
        # existing task).  Stored as 'YYYY-MM-DD' and 'HH:MM'.
        if "deadline_date" not in task_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN deadline_date TEXT")
        if "deadline_time" not in task_columns:
            cursor.execute("ALTER TABLE tasks ADD COLUMN deadline_time TEXT")

        # Migration: who wrote an assistant message -- 'engine' (answers from the
        # database) or 'llm' (the language model).  NULL for older messages.
        cursor.execute("PRAGMA table_info(ai_messages)")
        if "source" not in {row["name"] for row in cursor.fetchall()}:
            cursor.execute("ALTER TABLE ai_messages ADD COLUMN source TEXT")

        self.conn.commit()

    def seed_demo_users(self) -> None:
        """Insert the two demo accounts (approved) when the table is empty.

        Seeding only ever inserts; it never deletes or updates rows, so pending
        signup requests are always left untouched.
        """
        count = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count:
            return

        self.conn.executemany(
            "INSERT INTO users (username, password, role, full_name, status)"
            " VALUES (?, ?, ?, ?, 'approved')",
            [
                ("manager", "1234", "manager", "Admin Manager"),
                ("marwan", "1234", "employee", "Marwan Hatem"),
            ],
        )
        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _today():
        """Local calendar date as ``YYYY-MM-DD``.

        Every date comparison goes through this helper (instead of SQLite's
        ``date('now')``, which is UTC) so that a session written at 01:00 local
        time is still found by the "today" and "last 7 days" queries.
        """
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _time_now():
        """Local wall-clock time as ``HH:MM:SS``."""
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _fetch_all(cursor):
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _fetch_one(cursor):
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    # ------------------------------------------------------------------ #
    #  Users
    # ------------------------------------------------------------------ #
    def get_user(self, username: str, password: str, role: str) -> Optional[Dict[str, Any]]:
        """Return the matching user as a dict, or ``None`` when login fails."""
        cursor = self.conn.execute(
            "SELECT * FROM users WHERE username=? AND password=? AND role=?",
            (username, password, role),
        )
        return self._fetch_one(cursor)

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """One user row (dict) by id, or None."""
        cursor = self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,))
        return self._fetch_one(cursor)

    def get_all_employees(self) -> List[Dict[str, Any]]:
        """Every account with role 'employee' (any status), sorted by name."""
        cursor = self.conn.execute(
            "SELECT * FROM users WHERE role='employee' ORDER BY full_name"
        )
        return self._fetch_all(cursor)

    def update_user_profile(self, user_id: int, *, full_name=None, username=None):
        """Update only the provided fields. Returns ``(ok, message)``."""
        updates = []
        params = []

        if full_name is not None:
            full_name = str(full_name).strip()
            if not full_name:
                return False, "Full name cannot be empty"
            updates.append("full_name=?")
            params.append(full_name)

        if username is not None:
            username = str(username).strip()
            if not username:
                return False, "Username cannot be empty"
            taken = self.conn.execute(
                "SELECT id FROM users WHERE username=? AND id<>?",
                (username, user_id),
            ).fetchone()
            if taken:
                return False, "Username already exists"
            updates.append("username=?")
            params.append(username)

        if not updates:
            return False, "Nothing to update"

        try:
            params.append(user_id)
            cursor = self.conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id=?", tuple(params)
            )
            self.conn.commit()
        except sqlite3.Error as error:
            self.conn.rollback()
            return False, str(error)
        if cursor.rowcount == 0:
            return False, "User not found"
        return True, "Profile updated"

    def update_user_password(self, user_id: int, new_password):
        """Set a new password (at least 4 characters). Returns ``(ok, message)``."""
        if new_password is None or len(str(new_password)) < 4:
            return False, "Password must be at least 4 characters"
        try:
            cursor = self.conn.execute(
                "UPDATE users SET password=? WHERE id=?", (new_password, user_id)
            )
            self.conn.commit()
        except sqlite3.Error as error:
            self.conn.rollback()
            return False, str(error)
        if cursor.rowcount == 0:
            return False, "User not found"
        return True, "Password updated"

    # ------------------------------------------------------------------ #
    #  Signup requests / approval workflow
    # ------------------------------------------------------------------ #
    def create_signup_request(self, username: str, password: str, full_name: str):
        """Insert a new employee with status='pending'. Returns (ok, msg)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            return False, "Username already exists"

        try:
            cursor.execute(
                "INSERT INTO users (username, password, role, full_name, status)"
                " VALUES (?, ?, 'employee', ?, 'pending')",
                (username, password, full_name),
            )
            self.conn.commit()
            return True, "Signup submitted"
        except Exception as error:
            return False, str(error)

    def get_pending_users(self):
        """Employees whose signup request is still waiting for approval."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, username, full_name, status FROM users"
            " WHERE role = 'employee' AND status = 'pending'"
            " ORDER BY id DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def approve_user(self, user_id: int) -> None:
        """Let a pending user log in."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
        self.conn.commit()

    def reject_user(self, user_id: int) -> None:
        """Refuse a pending signup request."""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE users SET status = 'rejected' WHERE id = ?", (user_id,))
        self.conn.commit()

    def get_user_status(self, username: str, role: str):
        """Return the status string, or None if the user doesn't exist."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT status FROM users WHERE username = ? AND role = ?",
            (username, role),
        )
        row = cursor.fetchone()
        return row["status"] if row else None

    # ------------------------------------------------------------------ #
    #  Sessions
    # ------------------------------------------------------------------ #
    def create_session(self, user_id: int) -> int:
        """Open a session for ``user_id`` and return its new row id."""
        cursor = self.conn.execute(
            "INSERT INTO sessions"
            " (user_id, date, start_time, end_time, focus_seconds,"
            "  away_seconds, distractions)"
            " VALUES (?, ?, ?, NULL, 0, 0, 0)",
            (user_id, self._today(), self._time_now()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def end_session(self, session_id, focus_seconds, away_seconds, *,
                    distraction_seconds=0,
                    screen_productive=0, screen_distracted=0, screen_idle=0):
        """Close a session and store its final counters (camera + screen).

        ``distraction_seconds`` is the tracked distraction *time*; the legacy
        ``distractions`` count column is left untouched (historical rows keep
        their values, new rows stay at 0).
        """
        self.conn.execute(
            "UPDATE sessions SET end_time=?, focus_seconds=?, away_seconds=?,"
            " distraction_seconds=?, screen_productive_seconds=?,"
            " screen_distracted_seconds=?, screen_idle_seconds=? WHERE id=?",
            (
                self._time_now(),
                int(focus_seconds),
                int(away_seconds),
                int(distraction_seconds),
                int(screen_productive),
                int(screen_distracted),
                int(screen_idle),
                session_id,
            ),
        )
        self.conn.commit()

    def get_today_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        """Today's sessions of one user, newest first."""
        cursor = self.conn.execute(
            "SELECT * FROM sessions WHERE user_id=? AND date=?"
            " ORDER BY start_time DESC",
            (user_id, self._today()),
        )
        return self._fetch_all(cursor)

    def get_all_sessions_today(self) -> List[Dict[str, Any]]:
        """Today's sessions of everybody (with the user's name), newest first."""
        cursor = self.conn.execute(
            "SELECT s.*, u.full_name, u.username"
            " FROM sessions s JOIN users u ON s.user_id = u.id"
            " WHERE s.date = ? ORDER BY s.start_time DESC",
            (self._today(),),
        )
        return self._fetch_all(cursor)

    def get_weekly_report(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Aggregate the last 7 days (today included) for one user."""
        cursor = self.conn.execute(
            "SELECT COALESCE(SUM(focus_seconds),0)         AS total_focus,"
            "       COALESCE(SUM(away_seconds),0)          AS total_away,"
            "       COALESCE(SUM(distraction_seconds),0)   AS total_distraction,"
            "       COUNT(*)                               AS total_sessions"
            " FROM sessions"
            " WHERE user_id=? AND date >= date(?, '-6 days')",
            (user_id, self._today()),
        )
        return self._fetch_one(cursor)

    # ------------------------------------------------------------------ #
    #  Manager dashboard aggregates
    # ------------------------------------------------------------------ #
    def get_active_session_count_today(self):
        """Number of sessions that are still running today."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) AS active FROM sessions"
            " WHERE date=? AND end_time IS NULL",
            (self._today(),),
        )
        row = self._fetch_one(cursor)
        return row["active"] if row else 0

    def get_today_totals(self) -> Optional[Dict[str, Any]]:
        """Team-wide totals for today (three durations)."""
        cursor = self.conn.execute(
            "SELECT COALESCE(SUM(focus_seconds),0)        AS focus_seconds,"
            "       COALESCE(SUM(distraction_seconds),0)  AS distraction_seconds,"
            "       COALESCE(SUM(away_seconds),0)         AS away_seconds"
            " FROM sessions WHERE date=?",
            (self._today(),),
        )
        return self._fetch_one(cursor) or {
            "focus_seconds": 0, "distraction_seconds": 0, "away_seconds": 0
        }

    def get_today_totals_per_user(self):
        """Today's focus / distraction / away seconds for every employee."""
        totals = {
            row["user_id"]: row
            for row in self.conn.execute(
                "SELECT user_id,"
                "       COALESCE(SUM(focus_seconds),0)        AS focus_seconds,"
                "       COALESCE(SUM(distraction_seconds),0)  AS distraction_seconds,"
                "       COALESCE(SUM(away_seconds),0)         AS away_seconds"
                " FROM sessions WHERE date=? GROUP BY user_id",
                (self._today(),),
            ).fetchall()
        }

        per_user = []
        for user in self.get_all_employees():
            summary = totals.get(user["id"])
            per_user.append(
                {
                    "id": user["id"],
                    "full_name": user["full_name"],
                    "focus_seconds": summary["focus_seconds"] if summary else 0,
                    "distraction_seconds": (
                        summary["distraction_seconds"] if summary else 0
                    ),
                    "away_seconds": summary["away_seconds"] if summary else 0,
                }
            )
        return per_user

    def get_recent_events(self, limit: Optional[int] = 10) -> List[Dict[str, Any]]:
        """The newest events across all sessions, joined to the employee name."""
        cursor = self.conn.execute(
            "SELECT e.id, e.session_id, e.event_type, e.timestamp, u.full_name"
            " FROM events e"
            " JOIN sessions s ON s.id = e.session_id"
            " JOIN users u ON u.id = s.user_id"
            " ORDER BY e.id DESC LIMIT ?",
            (int(limit),),
        )
        return self._fetch_all(cursor)

    def get_absent_employees(self, days: int = 3) -> List[Dict[str, Any]]:
        """Employees without a single session in the last ``days`` days."""
        cursor = self.conn.execute(
            "SELECT u.id, u.full_name FROM users u"
            " WHERE u.role='employee' AND u.id NOT IN ("
            "     SELECT s.user_id FROM sessions s WHERE s.date >= date(?, ?)"
            " ) ORDER BY u.full_name",
            (self._today(), f"-{int(days) - 1} days"),
        )
        return self._fetch_all(cursor)

    def get_high_distraction_employees(self, threshold_seconds=3600) -> List[Dict[str, Any]]:
        """Employees whose distracted time today reached the threshold."""
        cursor = self.conn.execute(
            "SELECT u.id, u.full_name,"
            "       COALESCE(SUM(s.distraction_seconds),0) AS distraction_seconds"
            " FROM users u"
            " JOIN sessions s ON s.user_id = u.id"
            " WHERE s.date = ?"
            " GROUP BY u.id, u.full_name"
            " HAVING COALESCE(SUM(s.distraction_seconds),0) >= ?"
            " ORDER BY distraction_seconds DESC",
            (self._today(), int(threshold_seconds)),
        )
        return self._fetch_all(cursor)

    def get_active_employees_today(self) -> List[Dict[str, Any]]:
        """Employees with a session still running today, as ``[{id, full_name}]``."""
        cursor = self.conn.execute(
            "SELECT DISTINCT u.id, u.full_name FROM sessions s"
            " JOIN users u ON u.id = s.user_id"
            " WHERE s.date = ? AND s.end_time IS NULL AND u.role = 'employee'"
            " ORDER BY u.full_name",
            (self._today(),),
        )
        return self._fetch_all(cursor)

    def get_employee_status_today(self):
        """Today's aggregated status for every employee.

        Returns ``[{id, full_name, status, focus_seconds, distraction_seconds,
        away_seconds}]`` where status is 'absent' (no session today),
        'distracted' (open session whose newest event is a distraction) or
        'present' otherwise.
        """
        totals = {
            row["user_id"]: row
            for row in self.conn.execute(
                "SELECT user_id,"
                "       COALESCE(SUM(focus_seconds),0)        AS focus_seconds,"
                "       COALESCE(SUM(distraction_seconds),0)  AS distraction_seconds,"
                "       COALESCE(SUM(away_seconds),0)         AS away_seconds,"
                "       MAX(CASE WHEN end_time IS NULL THEN id END) AS open_session_id"
                " FROM sessions WHERE date=? GROUP BY user_id",
                (self._today(),),
            ).fetchall()
        }

        employees = []
        for user in self.get_all_employees():
            summary = totals.get(user["id"])
            if summary is None:
                employees.append(
                    {
                        "id": user["id"],
                        "full_name": user["full_name"],
                        "status": "absent",
                        "focus_seconds": 0,
                        "distraction_seconds": 0,
                        "away_seconds": 0,
                    }
                )
                continue

            status = "present"
            open_session_id = summary["open_session_id"]
            if open_session_id:
                last_event = self.get_last_event(open_session_id)
                if last_event and last_event["event_type"] == "distraction":
                    status = "distracted"

            employees.append(
                {
                    "id": user["id"],
                    "full_name": user["full_name"],
                    "status": status,
                    "focus_seconds": summary["focus_seconds"],
                    "distraction_seconds": summary["distraction_seconds"],
                    "away_seconds": summary["away_seconds"],
                }
            )
        return employees

    def get_sessions_history(self, user_id: Optional[int] = None, days: int = 7) -> List[Dict[str, Any]]:
        """Sessions from the last ``days`` days, newest first.

        ``user_id=None`` returns every employee's sessions.  A ``days`` value of
        3650 or more means "all time".
        """
        query = (
            "SELECT s.id, s.user_id, u.full_name, s.date, s.start_time,"
            "       s.end_time, s.focus_seconds, s.distraction_seconds,"
            "       s.away_seconds, s.distractions,"
            "       s.screen_productive_seconds, s.screen_distracted_seconds,"
            "       s.screen_idle_seconds"
            " FROM sessions s JOIN users u ON u.id = s.user_id"
        )
        conditions = []
        params = []
        if days and int(days) < 3650:
            conditions.append("s.date >= date(?, ?)")
            params.extend([self._today(), f"-{int(days) - 1} days"])
        if user_id is not None:
            conditions.append("s.user_id = ?")
            params.append(user_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY s.date DESC, s.start_time DESC, s.id DESC"

        return self._fetch_all(self.conn.execute(query, tuple(params)))

    def get_session_events(self, session_id: int) -> List[Dict[str, Any]]:
        """All events of one session, oldest first."""
        cursor = self.conn.execute(
            "SELECT * FROM events WHERE session_id=? ORDER BY id ASC",
            (session_id,),
        )
        return self._fetch_all(cursor)

    def get_weekly_report_all(self):
        """Last-7-days aggregates for every employee (zeros when they have none)."""
        totals = {
            row["user_id"]: row
            for row in self.conn.execute(
                "SELECT user_id,"
                "       COALESCE(SUM(focus_seconds),0)        AS total_focus,"
                "       COALESCE(SUM(distraction_seconds),0)  AS total_distraction,"
                "       COALESCE(SUM(away_seconds),0)         AS total_away,"
                "       COUNT(*)                              AS total_sessions"
                " FROM sessions WHERE date >= date(?, '-6 days') GROUP BY user_id",
                (self._today(),),
            ).fetchall()
        }

        report = []
        for user in self.get_all_employees():
            summary = totals.get(user["id"])
            report.append(
                {
                    "id": user["id"],
                    "full_name": user["full_name"],
                    "total_focus": summary["total_focus"] if summary else 0,
                    "total_distraction": summary["total_distraction"] if summary else 0,
                    "total_away": summary["total_away"] if summary else 0,
                    "total_sessions": summary["total_sessions"] if summary else 0,
                }
            )
        return report

    # ------------------------------------------------------------------ #
    #  Events
    # ------------------------------------------------------------------ #
    def log_event(self, session_id: int, event_type: str) -> None:
        """Append a 'focus' / 'away' / 'distraction' event to a session."""
        self.conn.execute(
            "INSERT INTO events (session_id, event_type, timestamp)"
            " VALUES (?, ?, datetime('now','localtime'))",
            (session_id, event_type),
        )
        self.conn.commit()

    def get_last_event(self, session_id: int) -> Optional[Dict[str, Any]]:
        """The most recent focus/distraction/away event of a session, or None."""
        cursor = self.conn.execute(
            "SELECT * FROM events WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        return self._fetch_one(cursor)

    # ------------------------------------------------------------------ #
    #  Tasks
    # ------------------------------------------------------------------ #
    def get_tasks(self, user_id: int) -> List[Dict[str, Any]]:
        """All tasks of a user (assigned and personal): open first, newest first."""
        cursor = self.conn.execute(
            "SELECT * FROM tasks WHERE user_id=? ORDER BY is_done ASC, id DESC",
            (user_id,),
        )
        return self._fetch_all(cursor)

    def get_assigned_tasks(self, user_id: int) -> List[Dict[str, Any]]:
        """Tasks a manager assigned to this user: open first, newest first."""
        cursor = self.conn.execute(
            "SELECT * FROM tasks WHERE user_id=? AND assigned_by IS NOT NULL"
            " ORDER BY is_done ASC, id DESC",
            (user_id,),
        )
        return self._fetch_all(cursor)

    def get_self_tasks(self, user_id: int) -> List[Dict[str, Any]]:
        """The user's own (personal) tasks: open first, newest first."""
        cursor = self.conn.execute(
            "SELECT * FROM tasks WHERE user_id=? AND assigned_by IS NULL"
            " ORDER BY is_done ASC, id DESC",
            (user_id,),
        )
        return self._fetch_all(cursor)

    def add_task(self, user_id, title, priority="normal", assigned_by=None,
                 description=None, deadline_date=None, deadline_time=None):
        """Create a task and return its new row id.

        ``assigned_by``, ``description`` and the deadline (``'YYYY-MM-DD'`` plus
        an optional ``'HH:MM'``) may be None (stored as NULL).
        """
        cursor = self.conn.execute(
            "INSERT INTO tasks (user_id, assigned_by, title, is_done, priority,"
            " created_at, description, deadline_date, deadline_time)"
            " VALUES (?, ?, ?, 0, ?, datetime('now','localtime'), ?, ?, ?)",
            (user_id, assigned_by, title, priority, description,
             deadline_date, deadline_time if deadline_date else None),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_task_deadline(self, task_id: int, deadline_date: Optional[str], deadline_time: Optional[str] = None):
        """Set or clear the deadline of one task. Returns ``(ok, message)``.

        Pass ``deadline_date=None`` to clear the deadline (the time is cleared
        too).  A date without a time means "end of that day".
        """
        if deadline_date is None:
            deadline_time = None
        elif deadline_due_datetime(deadline_date, deadline_time) is None:
            return False, "Invalid deadline"
        try:
            cursor = self.conn.execute(
                "UPDATE tasks SET deadline_date=?, deadline_time=? WHERE id=?",
                (deadline_date, deadline_time, task_id),
            )
            self.conn.commit()
        except sqlite3.Error as error:
            self.conn.rollback()
            return False, str(error)
        if cursor.rowcount == 0:
            return False, "Task not found"
        return True, "Deadline updated"

    def get_upcoming_deadlines(self, user_id: int, within_hours=24):
        """Open tasks of ``user_id`` that are overdue or due within N hours.

        Each row is the task dict plus ``overdue`` (bool) and ``due_at``
        (``'YYYY-MM-DD HH:MM'``), soonest first.  Tasks that are done, or have
        no deadline, are never returned.
        """
        now = datetime.now()
        horizon = now + timedelta(hours=within_hours)
        cursor = self.conn.execute(
            "SELECT * FROM tasks WHERE user_id=? AND is_done=0"
            " AND deadline_date IS NOT NULL",
            (user_id,),
        )
        upcoming = []
        for task in self._fetch_all(cursor):
            due = deadline_due_datetime(task["deadline_date"], task["deadline_time"])
            if due is None or due > horizon:
                continue
            task["overdue"] = due < now
            task["due_at"] = due.strftime("%Y-%m-%d %H:%M")
            upcoming.append((due, task))
        upcoming.sort(key=lambda pair: pair[0])
        return [task for _due, task in upcoming]

    def toggle_task(self, task_id: int) -> None:
        """Flip a task between done and not done."""
        self.conn.execute(
            "UPDATE tasks SET is_done = CASE WHEN is_done=0 THEN 1 ELSE 0 END"
            " WHERE id=?",
            (task_id,),
        )
        self.conn.commit()

    def delete_task(self, task_id: int) -> None:
        """Delete one task by id."""
        self.conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  Calendar events
    # ------------------------------------------------------------------ #
    _EVENT_SELECT = (
        "SELECT e.id, e.title, e.description, e.event_date, e.start_time,"
        "       e.end_time, e.created_by, e.created_at,"
        "       u.full_name AS created_by_name,"
        "       (SELECT COUNT(*) FROM calendar_attendees a"
        "         WHERE a.event_id = e.id) AS attendee_count"
        " FROM calendar_events e JOIN users u ON u.id = e.created_by"
    )
    _EVENT_ORDER = " ORDER BY e.event_date, e.start_time IS NOT NULL, e.start_time, e.id"

    def create_calendar_event(self, title, event_date, created_by,
                              description=None, start_time=None, end_time=None):
        """Insert a new calendar event and return its id.

        ``event_date`` is ``'YYYY-MM-DD'``; ``start_time`` / ``end_time`` are
        ``'HH:MM'`` or None (an event without times lasts the whole day).
        """
        cursor = self.conn.execute(
            "INSERT INTO calendar_events (title, description, event_date,"
            " start_time, end_time, created_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))",
            (title, description, event_date, start_time, end_time, created_by),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_calendar_event(self, event_id, *, title=_UNSET, description=_UNSET,
                              event_date=_UNSET, start_time=_UNSET, end_time=_UNSET):
        """Update only the fields that are passed. Returns ``(ok, message)``.

        Omitting a field leaves it untouched; passing ``None`` clears it (only
        possible for the description and the two times -- the title and the date
        are required).
        """
        updates = []
        params = []
        if title is not _UNSET:
            if title is None or not str(title).strip():
                return False, "Title cannot be empty"
            updates.append("title=?")
            params.append(str(title).strip())
        if event_date is not _UNSET:
            if event_date is None or deadline_due_datetime(event_date) is None:
                return False, "Invalid date"
            updates.append("event_date=?")
            params.append(event_date)
        for column, value in (("description", description),
                              ("start_time", start_time),
                              ("end_time", end_time)):
            if value is not _UNSET:
                updates.append(f"{column}=?")
                params.append(value)
        if not updates:
            return False, "Nothing to update"

        try:
            params.append(event_id)
            cursor = self.conn.execute(
                f"UPDATE calendar_events SET {', '.join(updates)} WHERE id=?",
                tuple(params),
            )
            self.conn.commit()
        except sqlite3.Error as error:
            self.conn.rollback()
            return False, str(error)
        if cursor.rowcount == 0:
            return False, "Event not found"
        return True, "Event updated"

    def delete_calendar_event(self, event_id: int):
        """Delete an event together with its attendee links. Returns ``(ok, message)``."""
        try:
            self.conn.execute(
                "DELETE FROM calendar_attendees WHERE event_id=?", (event_id,)
            )
            cursor = self.conn.execute(
                "DELETE FROM calendar_events WHERE id=?", (event_id,)
            )
            self.conn.commit()
        except sqlite3.Error as error:
            self.conn.rollback()
            return False, str(error)
        if cursor.rowcount == 0:
            return False, "Event not found"
        return True, "Event deleted"

    def get_calendar_attendees(self, event_id: int) -> List[Dict[str, Any]]:
        """Attendees of one event as ``[{id, username, full_name}]``, by name."""
        cursor = self.conn.execute(
            "SELECT u.id, u.username, u.full_name FROM calendar_attendees a"
            " JOIN users u ON u.id = a.user_id WHERE a.event_id=?"
            " ORDER BY u.full_name",
            (event_id,),
        )
        return self._fetch_all(cursor)

    def get_calendar_event(self, event_id: int):
        """One event (with ``created_by_name``, ``attendee_count`` and the
        ``attendees`` list), or None when it does not exist."""
        cursor = self.conn.execute(
            self._EVENT_SELECT + " WHERE e.id=?", (event_id,)
        )
        event = self._fetch_one(cursor)
        if event is not None:
            event["attendees"] = self.get_calendar_attendees(event_id)
        return event

    def set_calendar_attendees(self, event_id: int, user_ids):
        """Replace the attendee list of an event. Returns ``(ok, message)``.

        The list is a *snapshot* taken at save time: choosing "All employees"
        in the dialog stores every approved employee of that moment, so someone
        approved later is not invited retroactively.  Delete + insert run in one
        transaction.
        """
        wanted = sorted({int(user_id) for user_id in user_ids})
        try:
            self.conn.execute(
                "DELETE FROM calendar_attendees WHERE event_id=?", (event_id,)
            )
            self.conn.executemany(
                "INSERT INTO calendar_attendees (event_id, user_id) VALUES (?, ?)",
                [(event_id, user_id) for user_id in wanted],
            )
            self.conn.commit()
        except sqlite3.Error as error:
            self.conn.rollback()
            return False, str(error)
        return True, "%d attendee(s) saved" % len(wanted)

    def get_calendar_events_for_user(self, user_id: int, from_date=None, to_date=None) -> List[Dict[str, Any]]:
        """Events visible to ``user_id``: the ones they created plus the ones
        they are invited to, optionally limited to ``from_date..to_date``
        (``'YYYY-MM-DD'``, inclusive).  A manager therefore never sees another
        manager's events unless invited.
        """
        query = (
            self._EVENT_SELECT
            + " WHERE (e.created_by = ? OR e.id IN"
            "   (SELECT event_id FROM calendar_attendees WHERE user_id = ?))"
        )
        params = [user_id, user_id]
        if from_date:
            query += " AND e.event_date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND e.event_date <= ?"
            params.append(to_date)
        return self._fetch_all(
            self.conn.execute(query + self._EVENT_ORDER, tuple(params))
        )

    def get_calendar_events_on_date(self, date_str, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Events on one date; with ``user_id`` only those they created or attend."""
        if user_id is None:
            query = self._EVENT_SELECT + " WHERE e.event_date = ?"
            params = (date_str,)
        else:
            query = (
                self._EVENT_SELECT
                + " WHERE e.event_date = ? AND (e.created_by = ? OR e.id IN"
                "   (SELECT event_id FROM calendar_attendees WHERE user_id = ?))"
            )
            params = (date_str, user_id, user_id)
        return self._fetch_all(self.conn.execute(query + self._EVENT_ORDER, params))

    def get_today_events(self, user_id: int):
        """Today's events for ``user_id`` (creator or attendee), earliest first."""
        return self.get_calendar_events_on_date(self._today(), user_id)

    # ------------------------------------------------------------------ #
    #  AI chat (conversations with the local assistant)
    # ------------------------------------------------------------------ #
    def create_ai_chat(self, user_id: int, title: Optional[str] = None) -> int:
        """Insert a new, empty chat for ``user_id`` and return its id."""
        cursor = self.conn.execute(
            "INSERT INTO ai_chats (user_id, title, created_at, updated_at)"
            " VALUES (?, ?, datetime('now','localtime'), datetime('now','localtime'))",
            (user_id, title),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_ai_chats(self, user_id: int) -> List[Dict[str, Any]]:
        """Chats of one user, most recently active first.

        Each row: ``id, title, created_at, updated_at, message_count`` plus
        ``last_message`` (the newest message text, or None) for the chat list.
        """
        cursor = self.conn.execute(
            "SELECT c.id, c.title, c.created_at, c.updated_at,"
            "       (SELECT COUNT(*) FROM ai_messages m WHERE m.chat_id = c.id)"
            "           AS message_count,"
            "       (SELECT m.content FROM ai_messages m WHERE m.chat_id = c.id"
            "         ORDER BY m.id DESC LIMIT 1) AS last_message"
            " FROM ai_chats c WHERE c.user_id = ?"
            " ORDER BY c.updated_at DESC, c.id DESC",
            (user_id,),
        )
        return self._fetch_all(cursor)

    def get_ai_chat(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Metadata of one chat (``id, user_id, title, created_at, updated_at``), or None."""
        cursor = self.conn.execute(
            "SELECT id, user_id, title, created_at, updated_at"
            " FROM ai_chats WHERE id = ?",
            (chat_id,),
        )
        return self._fetch_one(cursor)

    def update_ai_chat_title(self, chat_id: int, title: str):
        """Set the title of a chat. Returns ``(ok, message)``."""
        cursor = self.conn.execute(
            "UPDATE ai_chats SET title = ? WHERE id = ?", (title, chat_id)
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            return False, "Chat not found"
        return True, "Title updated"

    def delete_ai_chat(self, chat_id: int):
        """Delete a chat and all of its messages. Returns ``(ok, message)``."""
        try:
            self.conn.execute("DELETE FROM ai_messages WHERE chat_id = ?", (chat_id,))
            cursor = self.conn.execute("DELETE FROM ai_chats WHERE id = ?", (chat_id,))
            self.conn.commit()
        except sqlite3.Error as error:
            self.conn.rollback()
            return False, str(error)
        if cursor.rowcount == 0:
            return False, "Chat not found"
        return True, "Chat deleted"

    def add_ai_message(self, chat_id: int, role: str, content: str, source=None):
        """Append a message (``role`` is 'user' or 'assistant') to a chat.

        ``source`` says who wrote an assistant message: 'engine', 'llm' or None.

        Bumps the chat's ``updated_at`` so it moves to the top of the list.
        Returns the new message id, or None when the chat does not exist.
        """
        if role not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        if self.get_ai_chat(chat_id) is None:
            return None
        cursor = self.conn.execute(
            "INSERT INTO ai_messages (chat_id, role, content, created_at, source)"
            " VALUES (?, ?, ?, datetime('now','localtime'), ?)",
            (chat_id, role, content, source),
        )
        self.conn.execute(
            "UPDATE ai_chats SET updated_at = datetime('now','localtime')"
            " WHERE id = ?",
            (chat_id,),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_ai_messages(self, chat_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Messages of a chat, oldest first; with ``limit`` only the last N
        (still in chronological order)."""
        if limit:
            cursor = self.conn.execute(
                "SELECT * FROM (SELECT * FROM ai_messages WHERE chat_id = ?"
                " ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                (chat_id, int(limit)),
            )
        else:
            cursor = self.conn.execute(
                "SELECT * FROM ai_messages WHERE chat_id = ? ORDER BY id ASC",
                (chat_id,),
            )
        return self._fetch_all(cursor)

    def count_ai_messages(self, chat_id: int):
        """Number of messages in a chat."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM ai_messages WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]

    # ------------------------------------------------------------------ #
    #  Knowledge documents (assistant "RAG")
    # ------------------------------------------------------------------ #
    def upsert_knowledge_doc(self, filename: str, content: str, visibility: str = "everyone", uploaded_by=None):
        """Add a document, or replace the one with the same file name.

        Returns ``(doc_id, created)``.  ``visibility`` is 'everyone' or 'managers'.
        """
        if visibility not in ("everyone", "managers"):
            raise ValueError("visibility must be 'everyone' or 'managers'")
        filename = str(filename).strip()
        if not filename:
            raise ValueError("filename is required")
        size, words = len(content.encode("utf-8")), len(content.split())
        row = self.conn.execute(
            "SELECT id FROM knowledge_docs WHERE filename = ? COLLATE NOCASE", (filename,)
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE knowledge_docs SET content = ?, visibility = ?, uploaded_by = ?, size = ?,"
                " words = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (content, visibility, uploaded_by, size, words, row["id"]),
            )
            self.conn.commit()
            return row["id"], False
        cursor = self.conn.execute(
            "INSERT INTO knowledge_docs (filename, content, visibility, uploaded_by, size, words,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'),"
            " datetime('now','localtime'))",
            (filename, content, visibility, uploaded_by, size, words),
        )
        self.conn.commit()
        return cursor.lastrowid, True

    def get_knowledge_docs(self, include_manager_only=True, with_content=False) -> List[Dict[str, Any]]:
        """Documents sorted by file name.  Without ``include_manager_only`` the
        manager-only ones are never returned (employees use that)."""
        columns = "*" if with_content else (
            "id, filename, visibility, uploaded_by, size, words, created_at, updated_at")
        where = "" if include_manager_only else " WHERE visibility = 'everyone'"
        cursor = self.conn.execute(
            "SELECT %s FROM knowledge_docs%s ORDER BY filename COLLATE NOCASE" % (columns, where))
        return self._fetch_all(cursor)

    def get_knowledge_doc(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """One knowledge document including its text, or None."""
        return self._fetch_one(self.conn.execute("SELECT * FROM knowledge_docs WHERE id = ?", (doc_id,)))

    def delete_knowledge_doc(self, doc_id: int) -> bool:
        """Remove a document.  Returns True when something was deleted."""
        cursor = self.conn.execute("DELETE FROM knowledge_docs WHERE id = ?", (doc_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def set_knowledge_visibility(self, doc_id: int, visibility: str) -> bool:
        """Change who may read a document ('everyone' or 'managers'); True if it existed."""
        if visibility not in ("everyone", "managers"):
            raise ValueError("visibility must be 'everyone' or 'managers'")
        cursor = self.conn.execute(
            "UPDATE knowledge_docs SET visibility = ?, updated_at = datetime('now','localtime')"
            " WHERE id = ?", (visibility, doc_id))
        self.conn.commit()
        return cursor.rowcount > 0

    def knowledge_signature(self, include_manager_only=True):
        """A small value that changes whenever the documents someone can see change
        (used to know when a search index must be rebuilt)."""
        where = "" if include_manager_only else " WHERE visibility = 'everyone'"
        rows = self.conn.execute(
            "SELECT id, size, updated_at FROM knowledge_docs%s ORDER BY id" % where).fetchall()
        return tuple((r["id"], r["size"], r["updated_at"]) for r in rows)

    # ------------------------------------------------------------------ #
    #  Shutdown
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    #  Admin panel helpers (additive: the application never calls these)
    # ------------------------------------------------------------------ #
    def get_all_users(self) -> List[Dict[str, Any]]:
        """Every user row (passwords included), ordered by role then username."""
        cursor = self.conn.execute(
            "SELECT * FROM users ORDER BY role DESC, username ASC"
        )
        return self._fetch_all(cursor)

    def update_user(self, user_id, *, username=None, password=None,
                    role=None, status=None, full_name=None):
        """Update only the provided fields; returns the number of rows changed."""
        updates = []
        params = []
        for column, value in (
            ("username", username),
            ("password", password),
            ("role", role),
            ("status", status),
            ("full_name", full_name),
        ):
            if value is not None:
                updates.append(f"{column}=?")
                params.append(value)
        if not updates:
            return 0
        params.append(user_id)
        cursor = self.conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id=?", tuple(params)
        )
        self.conn.commit()
        return cursor.rowcount

    def username_taken(self, username: str, except_user_id: Optional[int] = None) -> bool:
        """True when another account already uses ``username`` (``except_user_id`` is ignored)."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM users WHERE username=? AND id<>?",
            (username, -1 if except_user_id is None else except_user_id),
        ).fetchone()
        return row[0] > 0

    def create_user(self, username: str, password: str, role: str, full_name: str,
                    status: str = "approved") -> int:
        """Insert an account directly (the admin panel's "Add user"); returns its id.

        Raises ``sqlite3.IntegrityError`` when the username is taken.
        """
        cursor = self.conn.execute(
            "INSERT INTO users (username, password, role, full_name, status) VALUES (?, ?, ?, ?, ?)",
            (username, password, role, full_name, status),
        )
        self.conn.commit()
        return cursor.lastrowid

    def count_user_related_rows(self, user_id: int) -> Dict[str, int]:
        """How many rows would disappear with this user: sessions, events, tasks,
        calendar entries and assistant chats (shown before the admin confirms a delete)."""
        one = lambda sql, *params: self.conn.execute(sql, params).fetchone()[0]
        return {
            "sessions": one("SELECT COUNT(*) FROM sessions WHERE user_id=?", user_id),
            "events": one("SELECT COUNT(*) FROM events WHERE session_id IN"
                          " (SELECT id FROM sessions WHERE user_id=?)", user_id),
            "tasks": one("SELECT COUNT(*) FROM tasks WHERE user_id=? OR assigned_by=?", user_id, user_id),
            "calendar": one("SELECT (SELECT COUNT(*) FROM calendar_events WHERE created_by=?)"
                            " + (SELECT COUNT(*) FROM calendar_attendees WHERE user_id=?)", user_id, user_id),
            "chats": one("SELECT COUNT(*) FROM ai_chats WHERE user_id=?", user_id),
        }

    def delete_all_tasks(self) -> int:
        """Delete every task of everybody; returns how many were removed."""
        cursor = self.conn.execute("DELETE FROM tasks")
        self.conn.commit()
        return cursor.rowcount

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """One session row with its owner's ``full_name``, or None."""
        return self._fetch_one(self.conn.execute(
            "SELECT s.*, u.full_name FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id=?",
            (session_id,),
        ))

    def delete_user_cascade(self, user_id: int):
        """Delete a user with every row that belongs to them, in one transaction.

        Returns a dict with the number of rows removed per table.
        """
        removed = {"events": 0, "sessions": 0, "tasks": 0, "calendar_events": 0,
                   "ai_chats": 0, "users": 0}
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.conn.execute(
                "DELETE FROM events WHERE session_id IN"
                " (SELECT id FROM sessions WHERE user_id=?)",
                (user_id,),
            )
            removed["events"] = cursor.rowcount

            cursor = self.conn.execute(
                "DELETE FROM sessions WHERE user_id=?", (user_id,)
            )
            removed["sessions"] = cursor.rowcount

            cursor = self.conn.execute(
                "DELETE FROM tasks WHERE user_id=? OR assigned_by=?",
                (user_id, user_id),
            )
            removed["tasks"] = cursor.rowcount

            # Calendar footprint: their invitations to other people's events, and
            # the events they created (with everybody's invitations to them).
            self.conn.execute(
                "DELETE FROM calendar_attendees WHERE user_id=?", (user_id,)
            )
            self.conn.execute(
                "DELETE FROM calendar_attendees WHERE event_id IN"
                " (SELECT id FROM calendar_events WHERE created_by=?)",
                (user_id,),
            )
            cursor = self.conn.execute(
                "DELETE FROM calendar_events WHERE created_by=?", (user_id,)
            )
            removed["calendar_events"] = cursor.rowcount

            # Assistant conversations (explicit, in addition to the FK cascade).
            self.conn.execute(
                "DELETE FROM ai_messages WHERE chat_id IN"
                " (SELECT id FROM ai_chats WHERE user_id=?)",
                (user_id,),
            )
            cursor = self.conn.execute(
                "DELETE FROM ai_chats WHERE user_id=?", (user_id,)
            )
            removed["ai_chats"] = cursor.rowcount

            cursor = self.conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            removed["users"] = cursor.rowcount

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return removed

    def delete_session(self, session_id: int):
        """Delete one session and its events in a transaction."""
        return self.delete_sessions_by_ids([session_id])

    def delete_sessions_by_ids(self, ids):
        """Bulk-delete sessions (and their events) in one transaction."""
        id_list = [int(value) for value in ids]
        removed = {"events": 0, "sessions": 0}
        if not id_list:
            return removed
        placeholders = ",".join("?" for _ in id_list)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.conn.execute(
                f"DELETE FROM events WHERE session_id IN ({placeholders})",
                tuple(id_list),
            )
            removed["events"] = cursor.rowcount
            cursor = self.conn.execute(
                f"DELETE FROM sessions WHERE id IN ({placeholders})",
                tuple(id_list),
            )
            removed["sessions"] = cursor.rowcount
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return removed

    def delete_sessions_filtered(self, user_id: Optional[int] = None, days: Optional[int] = None):
        """Bulk delete by user and/or date range (``days=None`` means all time)."""
        conditions = []
        params = []
        if days and int(days) < 3650:
            conditions.append("date >= date(?, ?)")
            params.extend([self._today(), f"-{int(days) - 1} days"])
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(int(user_id))
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        cursor = self.conn.execute(
            f"SELECT id FROM sessions{where}", tuple(params)
        )
        return self.delete_sessions_by_ids([row["id"] for row in cursor.fetchall()])

    def get_all_events(self, user_id: Optional[int] = None, event_type: Optional[str] = None, days: Optional[int] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Filtered events joined to their user, newest first."""
        query = (
            "SELECT e.id, e.session_id, e.event_type, e.timestamp,"
            "       u.full_name, u.username, s.user_id, s.date"
            " FROM events e"
            " JOIN sessions s ON s.id = e.session_id"
            " JOIN users u ON u.id = s.user_id"
        )
        conditions = []
        params = []
        if days and int(days) < 3650:
            conditions.append("s.date >= date(?, ?)")
            params.extend([self._today(), f"-{int(days) - 1} days"])
        if user_id is not None:
            conditions.append("s.user_id = ?")
            params.append(int(user_id))
        if event_type:
            conditions.append("e.event_type = ?")
            params.append(event_type)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY e.id DESC"
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))
        return self._fetch_all(self.conn.execute(query, tuple(params)))

    def delete_event(self, event_id: int):
        """Delete a single event."""
        cursor = self.conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        self.conn.commit()
        return cursor.rowcount

    def get_all_tasks(self, user_id: Optional[int] = None, priority: Optional[str] = None, done=None) -> List[Dict[str, Any]]:
        """Filtered tasks joined to their owner and the assigning manager."""
        query = (
            "SELECT t.*, u.full_name, u.username,"
            "       a.full_name AS assigned_by_name"
            " FROM tasks t"
            " LEFT JOIN users u ON u.id = t.user_id"
            " LEFT JOIN users a ON a.id = t.assigned_by"
        )
        conditions = []
        params = []
        if user_id is not None:
            conditions.append("t.user_id = ?")
            params.append(int(user_id))
        if priority:
            conditions.append("t.priority = ?")
            params.append(priority)
        if done is not None:
            conditions.append("t.is_done = ?")
            params.append(1 if done else 0)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY t.is_done ASC, t.id DESC"
        return self._fetch_all(self.conn.execute(query, tuple(params)))

    def clear_completed_tasks(self):
        """Delete every task marked done; returns how many were removed."""
        cursor = self.conn.execute("DELETE FROM tasks WHERE is_done=1")
        self.conn.commit()
        return cursor.rowcount

    def reset_employee_passwords(self, new_password="1234"):
        """Set the password of every *employee* account; returns rows changed."""
        cursor = self.conn.execute(
            "UPDATE users SET password=? WHERE role='employee'", (new_password,)
        )
        self.conn.commit()
        return cursor.rowcount

    def export_database(self, dest_path):
        """Write a consistent copy of the database to ``dest_path``."""
        dest = sqlite3.connect(dest_path)
        try:
            with dest:
                self.conn.backup(dest)
        finally:
            dest.close()
        return dest_path

    def import_database(self, src_path):
        """Replace the current database file with ``src_path`` and reconnect."""
        import shutil

        self.conn.commit()
        try:
            self.conn.close()
        except Exception:
            logger.debug("Closing the database connection failed", exc_info=True)

        shutil.copyfile(src_path, self.db_path)

        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.create_tables()          # migrate an older backup in place
        return self.db_path

    def factory_reset(self) -> bool:
        """Wipe all data, keeping only the two demo accounts (re-seeded).

        Users, sessions, events and tasks are cleared in one transaction and the
        demo accounts are restored to their documented credentials.
        """
        demo_users = (
            ("manager", "1234", "manager", "Admin Manager"),
            ("marwan", "1234", "employee", "Marwan Hatem"),
        )
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute("DELETE FROM ai_messages")
            self.conn.execute("DELETE FROM ai_chats")
            self.conn.execute("DELETE FROM knowledge_docs")
            self.conn.execute("DELETE FROM calendar_attendees")
            self.conn.execute("DELETE FROM calendar_events")
            self.conn.execute("DELETE FROM events")
            self.conn.execute("DELETE FROM sessions")
            self.conn.execute("DELETE FROM tasks")
            self.conn.execute(
                "DELETE FROM users WHERE username NOT IN ('manager', 'marwan')"
            )
            for username, password, role, full_name in demo_users:
                row = self.conn.execute(
                    "SELECT id FROM users WHERE username=?", (username,)
                ).fetchone()
                if row is None:
                    self.conn.execute(
                        "INSERT INTO users (username, password, role, full_name,"
                        " status) VALUES (?, ?, ?, ?, 'approved')",
                        (username, password, role, full_name),
                    )
                else:
                    self.conn.execute(
                        "UPDATE users SET password=?, role=?, full_name=?,"
                        " status='approved' WHERE id=?",
                        (password, role, full_name, row["id"]),
                    )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        self.conn.execute("VACUUM")
        return True

    def table_counts(self):
        """Row counts per table (used by the admin status bar)."""
        counts = {}
        for table in ("users", "sessions", "events", "tasks"):
            counts[table] = self.conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        return counts

    def close(self) -> None:
        """Close the connection (safe to call twice)."""
        try:
            self.conn.close()
        except Exception:
            logger.debug("Closing the database connection failed", exc_info=True)


# ---------------------------------------------------------------------- #
#  Self-test: python database/db_manager.py
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import tempfile

    print("=" * 64)
    print("DatabaseManager self-test")
    print("=" * 64)

    # 1. The default database is created, migrated, seeded and usable straight
    #    away.  (The real database may contain signup requests, so this only
    #    asserts the demo accounts are present and approved.)
    default_db = DatabaseManager()
    print("default database   : %s" % default_db.db_path)

    default_columns = {
        row["name"]
        for row in default_db.conn.execute("PRAGMA table_info(users)").fetchall()
    }
    assert "status" in default_columns, "users.status column is missing"
    print("users columns      : %s" % ", ".join(sorted(default_columns)))

    demo_users = {
        row["username"]: row
        for row in default_db.conn.execute(
            "SELECT username, role, status FROM users WHERE username IN"
            " ('manager', 'marwan')"
        ).fetchall()
    }
    assert demo_users["manager"]["role"] == "manager"
    assert demo_users["marwan"]["role"] == "employee"
    assert demo_users["manager"]["status"] == "approved"
    assert demo_users["marwan"]["status"] == "approved"
    total_users = default_db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print("rows in users      : %d (demo accounts approved)" % total_users)

    session_columns = {
        row["name"]
        for row in default_db.conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    for column in (
        "screen_productive_seconds",
        "screen_distracted_seconds",
        "screen_idle_seconds",
    ):
        assert column in session_columns, f"sessions.{column} column is missing"
    print("sessions columns   : screen_* = %s" % ", ".join(
        sorted(c for c in session_columns if c.startswith("screen_"))
    ))
    default_db.close()

    # 2. Migration: a legacy database without users.status gets the column added
    #    in place and its existing rows become 'approved'.
    with tempfile.TemporaryDirectory() as tmp_dir:
        legacy_path = os.path.join(tmp_dir, "legacy.db")
        legacy = sqlite3.connect(legacy_path)
        legacy.executescript(
            "CREATE TABLE users ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " username TEXT UNIQUE NOT NULL,"
            " password TEXT NOT NULL,"
            " role TEXT NOT NULL,"
            " full_name TEXT NOT NULL);"
            "INSERT INTO users (username, password, role, full_name)"
            " VALUES ('marwan', '1234', 'employee', 'Marwan Hatem');"
        )
        legacy.commit()
        legacy.close()

        migrated = DatabaseManager(legacy_path)
        migrated_columns = {
            row["name"]
            for row in migrated.conn.execute("PRAGMA table_info(users)").fetchall()
        }
        assert "status" in migrated_columns, "migration did not add users.status"
        assert migrated.get_user_status("marwan", "employee") == "approved"
        assert migrated.get_pending_users() == []
        print("migration          : legacy users table upgraded, existing row is"
              " 'approved'")
        migrated.close()

    # 3. All other write tests run against a throwaway database so this
    #    self-test can be repeated without touching real data.
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = DatabaseManager(os.path.join(tmp_dir, "selftest.db"))
        try:
            manager = db.get_user("manager", "1234", "manager")
            employee = db.get_user("marwan", "1234", "employee")
            assert manager is not None, "manager demo user not found"
            assert employee is not None, "employee demo user not found"
            print(
                "seeded users       : %s/%s (%s), %s/%s (%s)"
                % (
                    manager["username"], manager["password"], manager["role"],
                    employee["username"], employee["password"], employee["role"],
                )
            )

            assert db.get_user("marwan", "wrong", "employee") is None
            assert db.get_user("marwan", "1234", "manager") is None
            assert db.get_user_by_id(employee["id"])["full_name"] == "Marwan Hatem"
            assert db.get_user_by_id(10 ** 6) is None
            assert [e["username"] for e in db.get_all_employees()] == ["marwan"]
            print("lookups            : wrong password and wrong role both rejected")

            session_id = db.create_session(employee["id"])
            db.log_event(session_id, "focus")
            db.log_event(session_id, "distraction")
            db.log_event(session_id, "away")
            last_event = db.get_last_event(session_id)
            print(
                "session            : id=%d, last event=%s @ %s"
                % (session_id, last_event["event_type"], last_event["timestamp"])
            )
            assert last_event["event_type"] == "away"
            assert db.get_last_event(10 ** 6) is None

            db.end_session(
                session_id, 3600, 120,
                distraction_seconds=42,
                screen_productive=2100, screen_distracted=180, screen_idle=60,
            )
            today = db.get_today_sessions(employee["id"])
            assert len(today) == 1, "session not returned by get_today_sessions"
            assert today[0]["focus_seconds"] == 3600
            assert today[0]["away_seconds"] == 120
            assert today[0]["distraction_seconds"] == 42, today[0]["distraction_seconds"]
            assert today[0]["distractions"] == 0, "the legacy count must stay 0"
            assert today[0]["end_time"] is not None
            assert today[0]["screen_productive_seconds"] == 2100
            assert today[0]["screen_distracted_seconds"] == 180
            assert today[0]["screen_idle_seconds"] == 60
            print(
                "distraction time   : %ds stored (legacy count=%d)"
                % (today[0]["distraction_seconds"], today[0]["distractions"])
            )
            print(
                "screen columns     : worked=%ds distracted=%ds idle=%ds"
                % (
                    today[0]["screen_productive_seconds"],
                    today[0]["screen_distracted_seconds"],
                    today[0]["screen_idle_seconds"],
                )
            )

            all_today = db.get_all_sessions_today()
            assert len(all_today) == 1
            assert all_today[0]["full_name"] == "Marwan Hatem"
            assert all_today[0]["username"] == "marwan"
            print(
                "sessions today     : %d row(s), joined to %s"
                % (len(all_today), all_today[0]["full_name"])
            )

            report = db.get_weekly_report(employee["id"])
            assert report["total_focus"] == 3600
            assert report["total_away"] == 120
            assert report["total_distraction"] == 42, report
            assert report["total_sessions"] == 1
            print(
                "weekly report      : focus=%ds distraction=%ds away=%ds sessions=%d"
                % (
                    report["total_focus"], report["total_distraction"],
                    report["total_away"], report["total_sessions"],
                )
            )

            # --- manager dashboard aggregates ------------------------------ #
            status_today = db.get_employee_status_today()
            marwan = next(r for r in status_today if r["full_name"] == "Marwan Hatem")
            assert set(marwan) == {
                "id", "full_name", "status", "focus_seconds",
                "distraction_seconds", "away_seconds",
            }, set(marwan)
            assert marwan["status"] == "present", marwan
            assert marwan["focus_seconds"] == 3600 and marwan["away_seconds"] == 120
            assert marwan["distraction_seconds"] == 42, marwan
            print(
                "status today       : %s -> %s (focus=%ds distraction=%ds away=%ds)"
                % (marwan["full_name"], marwan["status"], marwan["focus_seconds"],
                   marwan["distraction_seconds"], marwan["away_seconds"])
            )

            # An open session whose newest event is a distraction is 'distracted'.
            open_id = db.create_session(employee["id"])
            db.log_event(open_id, "focus")
            open_status = next(
                r for r in db.get_employee_status_today()
                if r["full_name"] == "Marwan Hatem"
            )["status"]
            assert open_status == "present", open_status
            db.log_event(open_id, "distraction")
            distracted_status = next(
                r for r in db.get_employee_status_today()
                if r["full_name"] == "Marwan Hatem"
            )["status"]
            assert distracted_status == "distracted", distracted_status
            db.end_session(open_id, 30, 0, distraction_seconds=1)
            print("status transitions : open session -> present, after a distraction"
                  " event -> distracted")

            # Every employee may still be absent (no session at all today):
            # create one who never started a session.
            assert db.create_signup_request("idle_user", "1234", "Idle Employee")[0]
            idle_id = db.get_pending_users()[0]["id"]
            db.approve_user(idle_id)

            idle_status = next(
                row for row in db.get_employee_status_today()
                if row["full_name"] == "Idle Employee"
            )
            assert idle_status["status"] == "absent", idle_status
            assert idle_status["focus_seconds"] == 0
            print("absent employee    : 'Idle Employee' reported as absent with zeros")

            history = db.get_sessions_history()
            assert len(history) >= 2, len(history)
            assert all(
                set(row) >= {
                    "id", "user_id", "full_name", "date", "start_time", "end_time",
                    "focus_seconds", "distraction_seconds", "away_seconds",
                    "screen_productive_seconds", "screen_distracted_seconds",
                    "screen_idle_seconds",
                }
                for row in history
            ), "history rows are missing columns"
            assert history[0]["id"] >= history[-1]["id"], "history is not newest first"
            assert all(row["full_name"] == "Marwan Hatem" for row in history)
            print("sessions history   : %d row(s) in the last 7 days, newest first"
                  % len(history))

            only_marwan = db.get_sessions_history(user_id=employee["id"])
            assert len(only_marwan) == len(history)
            assert db.get_sessions_history(user_id=10 ** 6) == []
            assert len(db.get_sessions_history(days=1)) >= 1
            assert len(db.get_sessions_history(days=3650)) == len(history)
            print("history filters    : user filter and 'all time' range honoured")

            events = db.get_session_events(session_id)
            assert [e["event_type"] for e in events] == ["focus", "distraction", "away"], \
                [e["event_type"] for e in events]
            assert all(events[i]["id"] < events[i + 1]["id"] for i in range(len(events) - 1)), \
                "events are not oldest first"
            assert db.get_session_events(10 ** 6) == []
            print("session events     : %d event(s) oldest first -> %s"
                  % (len(events), [e["event_type"] for e in events]))

            all_report = db.get_weekly_report_all()
            names = {row["full_name"] for row in all_report}
            assert "Marwan Hatem" in names, names
            marwan_report = next(r for r in all_report if r["full_name"] == "Marwan Hatem")
            assert set(marwan_report) == {
                "id", "full_name", "total_focus", "total_distraction",
                "total_away", "total_sessions",
            }, set(marwan_report)
            assert marwan_report["total_focus"] == 3600 + 30
            assert marwan_report["total_sessions"] == 2
            assert len(all_report) == len(db.get_all_employees()), "every employee missing"
            idle_report = next(
                row for row in all_report if row["full_name"] == "Idle Employee"
            )
            assert idle_report["total_sessions"] == 0, idle_report
            assert idle_report["total_focus"] == 0 and idle_report["total_away"] == 0
            print(
                "weekly report all  : %d employees, marwan focus=%ds sessions=%d, "
                "zero-rows included"
                % (len(all_report), marwan_report["total_focus"],
                   marwan_report["total_sessions"])
            )

            # --- manager home dashboard aggregates ------------------------- #
            active = db.get_active_session_count_today()
            assert active == 0, active          # every session above was closed
            open_id = db.create_session(employee["id"])
            assert db.get_active_session_count_today() == 1
            db.end_session(open_id, 5, 0, distraction_seconds=1)
            assert db.get_active_session_count_today() == 0
            print("active sessions    : 0 -> 1 while a session is open -> 0")

            totals = db.get_today_totals()
            assert set(totals) == {"focus_seconds", "distraction_seconds",
                                   "away_seconds"}, set(totals)
            assert totals["focus_seconds"] == 3600 + 30 + 5, totals
            assert totals["away_seconds"] == 120
            # 42s (first session) + 1s + 1s from the two short sessions above.
            assert totals["distraction_seconds"] == 44, totals
            print("today totals       : focus=%ds distraction=%ds away=%ds"
                  % (totals["focus_seconds"], totals["distraction_seconds"],
                     totals["away_seconds"]))

            per_user = db.get_today_totals_per_user()
            assert len(per_user) == len(db.get_all_employees())
            assert all(set(row) == {"id", "full_name", "focus_seconds",
                                    "distraction_seconds", "away_seconds"}
                       for row in per_user)
            marwan_totals = next(r for r in per_user if r["full_name"] == "Marwan Hatem")
            assert marwan_totals["focus_seconds"] == totals["focus_seconds"]
            idle_totals = next(r for r in per_user if r["full_name"] == "Idle Employee")
            assert idle_totals["focus_seconds"] == 0
            print("today per user     : %d employees, marwan=%ds, idle user=%ds"
                  % (len(per_user), marwan_totals["focus_seconds"],
                     idle_totals["focus_seconds"]))

            recent = db.get_recent_events(limit=10)
            assert 1 <= len(recent) <= 10, len(recent)
            assert all(set(row) >= {"id", "session_id", "event_type", "timestamp",
                                    "full_name"} for row in recent)
            assert recent[0]["id"] > recent[-1]["id"], "recent events are not newest first"
            assert all(row["full_name"] for row in recent)
            print("recent events      : %d rows newest-first -> %s"
                  % (len(recent), [r["event_type"] for r in recent[:5]]))
            assert db.get_recent_events(limit=0) == []

            absent = db.get_absent_employees(days=3)
            assert any(row["full_name"] == "Idle Employee" for row in absent), absent
            assert not any(row["full_name"] == "Marwan Hatem" for row in absent)
            print("absent (3 days)    : %s" % [row["full_name"] for row in absent])
            # A user who never started a session is absent for any window.
            assert any(row["full_name"] == "Idle Employee"
                       for row in db.get_absent_employees(days=3650))
            assert not any(row["full_name"] == "Marwan Hatem"
                           for row in db.get_absent_employees(days=3650))

            high = db.get_high_distraction_employees(threshold_seconds=30)
            assert any(row["full_name"] == "Marwan Hatem" for row in high), high
            assert all(row["distraction_seconds"] >= 30 for row in high)
            assert db.get_high_distraction_employees(threshold_seconds=10 ** 6) == []
            print("high distraction   : %s (>=30s today)"
                  % [(row["full_name"], row["distraction_seconds"]) for row in high])
            assert db.get_weekly_report(10 ** 6)["total_sessions"] == 0

            assigned_id = db.add_task(
                employee["id"], "Prepare Q3 sales report",
                priority="urgent", assigned_by=manager["id"],
            )
            self_id = db.add_task(employee["id"], "Buy coffee beans")
            print("tasks added        : ids %d (assigned), %d (self)" % (assigned_id, self_id))

            assert len(db.get_tasks(employee["id"])) == 2
            assert [t["title"] for t in db.get_assigned_tasks(employee["id"])] == [
                "Prepare Q3 sales report"
            ]
            assert [t["title"] for t in db.get_self_tasks(employee["id"])] == [
                "Buy coffee beans"
            ]

            db.toggle_task(self_id)
            after_toggle = {t["id"]: t for t in db.get_tasks(employee["id"])}
            assert after_toggle[self_id]["is_done"] == 1
            db.toggle_task(self_id)
            after_toggle = {t["id"]: t for t in db.get_tasks(employee["id"])}
            assert after_toggle[self_id]["is_done"] == 0
            print("toggle_task        : done -> not done (is_done=1 then 0)")

            db.delete_task(assigned_id)
            assert len(db.get_tasks(employee["id"])) == 1
            print("delete_task        : removed task %d" % assigned_id)

            # --- task description (optional, NULL when omitted) ------------ #
            with_desc = db.add_task(
                employee["id"], "Buy milk", description="2% organic, 1L"
            )
            without_desc = db.add_task(employee["id"], "No notes here")
            by_id = {t["id"]: t for t in db.get_self_tasks(employee["id"])}
            assert "description" in by_id[with_desc], "description key missing"
            assert by_id[with_desc]["description"] == "2% organic, 1L"
            assert by_id[without_desc]["description"] is None
            manager_task = db.add_task(
                employee["id"], "Review budget", priority="urgent",
                assigned_by=manager["id"], description="Q3 numbers",
            )
            assigned = {t["id"]: t for t in db.get_assigned_tasks(employee["id"])}
            assert assigned[manager_task]["description"] == "Q3 numbers"
            print("task description   : stored text and NULL both read back")

            # --- task deadlines --------------------------------------------- #
            soon = (datetime.now() + timedelta(hours=3)).replace(second=0, microsecond=0)
            far = datetime.now() + timedelta(days=5)
            past = datetime.now() - timedelta(days=1)
            t_soon = db.add_task(
                employee["id"], "Due soon", assigned_by=manager["id"],
                deadline_date=soon.strftime("%Y-%m-%d"),
                deadline_time=soon.strftime("%H:%M"),
            )
            t_far = db.add_task(
                employee["id"], "Due later",
                deadline_date=far.strftime("%Y-%m-%d"), deadline_time="10:00",
            )
            t_past = db.add_task(
                employee["id"], "Overdue", deadline_date=past.strftime("%Y-%m-%d")
            )
            t_none = db.add_task(employee["id"], "No deadline")
            rows = {t["id"]: t for t in db.get_tasks(employee["id"])}
            assert rows[t_none]["deadline_date"] is None
            assert rows[t_none]["deadline_time"] is None
            assert rows[t_soon]["deadline_time"] == soon.strftime("%H:%M")
            upcoming = {t["id"]: t for t in db.get_upcoming_deadlines(employee["id"])}
            assert t_soon in upcoming and upcoming[t_soon]["overdue"] is False
            assert t_past in upcoming and upcoming[t_past]["overdue"] is True
            assert t_far not in upcoming and t_none not in upcoming
            # a date with no time falls due at the END of that day
            assert deadline_due_datetime("2026-10-27").strftime("%H:%M") == "23:59"
            assert deadline_due_datetime("2026-10-27", "14:00").strftime("%H:%M") == "14:00"
            assert deadline_due_datetime("garbage") is None
            # done tasks are never reported; deadlines can be changed and cleared
            db.toggle_task(t_past)
            assert t_past not in {t["id"] for t in db.get_upcoming_deadlines(employee["id"])}
            assert db.update_task_deadline(t_far, soon.strftime("%Y-%m-%d"),
                                           soon.strftime("%H:%M")) == (True, "Deadline updated")
            assert t_far in {t["id"] for t in db.get_upcoming_deadlines(employee["id"])}
            assert db.update_task_deadline(t_far, None)[0]
            cleared = {t["id"]: t for t in db.get_tasks(employee["id"])}[t_far]
            assert cleared["deadline_date"] is None and cleared["deadline_time"] is None
            assert db.update_task_deadline(t_far, "nope")[0] is False
            assert db.update_task_deadline(10 ** 6, "2026-10-27")[0] is False
            assert db.get_upcoming_deadlines(10 ** 6) == []
            print("task deadlines     : stored, soonest-first, overdue flag, clear/update OK")

            # --- calendar events -------------------------------------------- #
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            today_str = datetime.now().strftime("%Y-%m-%d")
            ev = db.create_calendar_event(
                "Standup", tomorrow, manager["id"], description="Daily sync",
                start_time="09:30", end_time="10:00",
            )
            assert db.set_calendar_attendees(ev, [employee["id"]])[0]
            got = db.get_calendar_event(ev)
            assert got["title"] == "Standup" and got["created_by_name"] == "Admin Manager"
            assert got["attendee_count"] == 1 and got["attendees"][0]["username"] == "marwan"
            assert got["start_time"] == "09:30" and got["description"] == "Daily sync"
            assert ev in {e["id"] for e in db.get_calendar_events_for_user(employee["id"])}
            assert ev in {e["id"] for e in db.get_calendar_events_for_user(manager["id"])}
            assert db.get_calendar_events_for_user(10 ** 6) == []
            assert db.get_calendar_events_for_user(manager["id"], from_date="2999-01-01") == []
            assert ev in {e["id"] for e in db.get_calendar_events_for_user(
                manager["id"], from_date=tomorrow, to_date=tomorrow)}
            assert db.get_calendar_event(10 ** 6) is None
            # a second manager only sees events they created or are invited to
            other = db.conn.execute(
                "INSERT INTO users (username, password, role, full_name, status)"
                " VALUES ('mgr2', '1234', 'manager', 'Second Manager', 'approved')"
            ).lastrowid
            db.conn.commit()
            assert db.get_calendar_events_for_user(other) == []
            db.set_calendar_attendees(ev, [employee["id"], other])
            assert ev in {e["id"] for e in db.get_calendar_events_for_user(other)}
            db.set_calendar_attendees(ev, [employee["id"]])
            # update: omitted fields stay, None clears, bad input is refused
            assert db.update_calendar_event(ev, title="Standup v2") == (True, "Event updated")
            kept = db.get_calendar_event(ev)
            assert kept["title"] == "Standup v2" and kept["description"] == "Daily sync"
            assert kept["start_time"] == "09:30"
            assert db.update_calendar_event(ev, description=None, start_time=None, end_time=None)[0]
            cleared = db.get_calendar_event(ev)
            assert cleared["description"] is None and cleared["start_time"] is None
            assert cleared["end_time"] is None and cleared["title"] == "Standup v2"
            assert db.update_calendar_event(ev, title="  ")[0] is False
            assert db.update_calendar_event(ev, event_date="not-a-date")[0] is False
            assert db.update_calendar_event(ev)[0] is False
            assert db.update_calendar_event(10 ** 6, title="x")[0] is False
            # today
            ev_today = db.create_calendar_event("Kickoff", today_str, manager["id"],
                                                start_time="14:00")
            ev_today_all = db.create_calendar_event("All day thing", today_str, manager["id"])
            db.set_calendar_attendees(ev_today, [employee["id"]])
            todays = [e["title"] for e in db.get_today_events(employee["id"])]
            assert todays == ["All day thing"][:0] + ["Kickoff"], todays
            on_date = [e["title"] for e in db.get_calendar_events_on_date(today_str)]
            assert on_date == ["All day thing", "Kickoff"], on_date   # no-time events first
            assert [e["title"] for e in db.get_calendar_events_on_date(
                today_str, manager["id"])] == ["All day thing", "Kickoff"]
            # delete removes the attendee links too
            assert db.delete_calendar_event(ev) == (True, "Event deleted")
            assert db.get_calendar_event(ev) is None
            assert db.conn.execute(
                "SELECT COUNT(*) FROM calendar_attendees WHERE event_id=?", (ev,)
            ).fetchone()[0] == 0
            assert db.delete_calendar_event(ev)[0] is False
            # deleting a USER must not trip the foreign keys: their invitations
            # and the events they created go with them
            db.create_signup_request("cal_user", "1234", "Calendar User")
            cal_user = db.get_user("cal_user", "1234", "employee")["id"]
            db.approve_user(cal_user)
            db.set_calendar_attendees(ev_today, [employee["id"], cal_user])
            own = db.create_calendar_event("Own event", tomorrow, cal_user)
            db.set_calendar_attendees(own, [employee["id"]])
            removed_cal = db.delete_user_cascade(cal_user)
            assert removed_cal["calendar_events"] == 1 and removed_cal["users"] == 1, removed_cal
            assert db.get_calendar_event(own) is None
            assert [a["id"] for a in db.get_calendar_attendees(ev_today)] == [employee["id"]]
            removed_mgr = db.delete_user_cascade(other)
            assert removed_mgr["users"] == 1
            db.delete_calendar_event(ev_today); db.delete_calendar_event(ev_today_all)
            print("calendar           : events, attendees, per-user visibility, user-delete cleanup OK")

            # --- AI chat ----------------------------------------------------- #
            chat_a = db.create_ai_chat(employee["id"])
            chat_b = db.create_ai_chat(employee["id"], title="Second chat")
            assert db.get_ai_chat(chat_a)["title"] is None
            assert db.get_ai_chat(chat_b)["title"] == "Second chat"
            assert db.get_ai_chat(10 ** 6) is None
            m1 = db.add_ai_message(chat_a, "user", "Hello")
            m2 = db.add_ai_message(chat_a, "assistant", "Hi there")
            m3 = db.add_ai_message(chat_a, "user", "What tasks do I have?")
            assert m1 < m2 < m3 and db.count_ai_messages(chat_a) == 3
            msgs = db.get_ai_messages(chat_a)
            assert [(m["role"], m["content"]) for m in msgs] == [
                ("user", "Hello"), ("assistant", "Hi there"),
                ("user", "What tasks do I have?")], msgs
            last_two = db.get_ai_messages(chat_a, limit=2)
            assert [m["content"] for m in last_two] == ["Hi there", "What tasks do I have?"]
            assert db.add_ai_message(10 ** 6, "user", "orphan") is None
            try:
                db.add_ai_message(chat_a, "robot", "x")
                raise AssertionError("bad role accepted")
            except ValueError:
                pass
            # list: newest activity first, with counts and a snippet
            db.conn.execute("UPDATE ai_chats SET updated_at='2000-01-01 00:00:00' WHERE id=?", (chat_b,))
            db.conn.execute("UPDATE ai_chats SET updated_at='2001-01-01 00:00:00' WHERE id=?", (chat_a,))
            db.conn.commit()
            listing = db.get_ai_chats(employee["id"])
            assert [c["id"] for c in listing] == [chat_a, chat_b], listing
            assert listing[0]["message_count"] == 3 and listing[1]["message_count"] == 0
            assert listing[0]["last_message"] == "What tasks do I have?" and listing[1]["last_message"] is None
            db.add_ai_message(chat_b, "user", "bump")
            assert db.get_ai_chats(employee["id"])[0]["id"] == chat_b, "new message must move the chat up"
            assert db.get_ai_chats(manager["id"]) == [], "chats are private to their owner"
            assert db.update_ai_chat_title(chat_a, "Renamed") == (True, "Title updated")
            assert db.get_ai_chat(chat_a)["title"] == "Renamed"
            assert db.update_ai_chat_title(10 ** 6, "x")[0] is False
            assert db.delete_ai_chat(chat_a) == (True, "Chat deleted")
            assert db.get_ai_chat(chat_a) is None and db.count_ai_messages(chat_a) == 0
            assert db.get_ai_messages(chat_a) == []
            assert db.delete_ai_chat(chat_a)[0] is False
            # deleting a user removes their chats and messages too
            db.create_signup_request("chat_user", "1234", "Chat User")
            chat_user = db.get_user("chat_user", "1234", "employee")["id"]
            db.approve_user(chat_user)
            doomed = db.create_ai_chat(chat_user, "bye")
            db.add_ai_message(doomed, "user", "x")
            removed_chat = db.delete_user_cascade(chat_user)
            assert removed_chat["ai_chats"] == 1 and removed_chat["users"] == 1, removed_chat
            assert db.get_ai_chat(doomed) is None and db.count_ai_messages(doomed) == 0
            db.delete_ai_chat(chat_b)
            print("ai chat            : create/list/rename/delete, ordering, privacy, user-delete cleanup OK")
            live = db.create_session(employee["id"])
            assert [e["id"] for e in db.get_active_employees_today()] == [employee["id"]]
            db.end_session(live, 1, 0)
            assert db.get_active_employees_today() == []

            # --- signup / approval workflow -------------------------------- #
            ok, message = db.create_signup_request("test1", "abcd", "Test User")
            assert ok and message == "Signup submitted"
            assert db.get_user_status("test1", "employee") == "pending"
            pending_row = db.get_user("test1", "abcd", "employee")
            assert pending_row is not None and pending_row["status"] == "pending"
            print("signup request     : test1 created with status='pending'")

            again_ok, again_msg = db.create_signup_request("test1", "abcd", "Test User")
            assert not again_ok and again_msg == "Username already exists"
            clash_ok, _ = db.create_signup_request("manager", "xxxx", "Name Clash")
            assert not clash_ok, "a manager username must not be reusable"
            print("duplicate username : rejected (%s)" % again_msg)

            pending = db.get_pending_users()
            assert [u["username"] for u in pending] == ["test1"]
            assert set(pending[0]) == {"id", "username", "full_name", "status"}
            assert db.get_user_status("nobody", "employee") is None
            print("get_pending_users  : %s" % [u["username"] for u in pending])

            # Re-seeding must never delete or change a pending request.
            db.seed_demo_users()
            assert db.get_user_status("test1", "employee") == "pending"
            print("seed_demo_users    : re-run left the pending request alone")

            db.approve_user(pending[0]["id"])
            assert db.get_user_status("test1", "employee") == "approved"
            assert db.get_pending_users() == []
            print("approve_user       : test1 is now 'approved'")

            db.create_signup_request("test2", "1234", "Another Guy")
            second = db.get_pending_users()[0]
            db.reject_user(second["id"])
            assert db.get_user_status("test2", "employee") == "rejected"
            assert db.get_pending_users() == []
            print("reject_user        : test2 is now 'rejected'")

            print("-" * 64)
            print(
                "summary            : users=%d employees=%d pending=%d sessions=%d"
                " events=%d tasks=%d"
                % (
                    db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                    len(db.get_all_employees()),
                    len(db.get_pending_users()),
                    db.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                    db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    db.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
                )
            )
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  Admin panel helpers: cascade delete + factory reset (temp DB only)
    # ------------------------------------------------------------------ #
    with tempfile.TemporaryDirectory() as admin_dir:
        admin_db = DatabaseManager(os.path.join(admin_dir, "admin_test.db"))
        try:
            admin_db.seed_demo_users()

            victim_id = admin_db.create_signup_request(
                "victim", "1234", "Victim Person"
            )[1] and admin_db.get_pending_users()[0]["id"]
            session_one = admin_db.create_session(victim_id)
            admin_db.log_event(session_one, "focus")
            admin_db.log_event(session_one, "away")
            admin_db.end_session(session_one, 100, 20, distraction_seconds=5)
            session_two = admin_db.create_session(victim_id)
            admin_db.end_session(session_two, 10, 2, distraction_seconds=1)
            admin_db.add_task(victim_id, "Victim task")
            admin_db.add_task(victim_id, "Assigned by the victim",
                              assigned_by=victim_id)

            users = admin_db.get_all_users()
            assert users and "password" in users[0].keys(), users[:1]
            print("admin get_all_users : %d rows (passwords included)" % len(users))

            assert admin_db.update_user(victim_id, full_name="Renamed Victim") == 1
            assert admin_db.update_user(victim_id, role="manager") == 1
            renamed = next(u for u in admin_db.get_all_users() if u["id"] == victim_id)
            assert renamed["full_name"] == "Renamed Victim"
            assert renamed["role"] == "manager"
            assert admin_db.update_user(victim_id) == 0, "no fields must change nothing"
            print("admin update_user  : name and role updated in place")

            assert len(admin_db.get_all_events(user_id=victim_id)) == 2
            assert len(admin_db.get_all_events(event_type="focus")) >= 1
            assert admin_db.get_all_events(days=1)
            assert len(admin_db.get_all_tasks(user_id=victim_id)) == 2
            assert len(admin_db.get_all_tasks(priority="normal")) == 2
            assert len(admin_db.get_all_tasks(done=False)) == 2
            print("admin filters      : events and tasks filter by user/type/state")

            removed = admin_db.delete_user_cascade(victim_id)
            assert removed == {"events": 2, "sessions": 2, "tasks": 2,
                               "calendar_events": 0, "ai_chats": 0, "users": 1}, removed
            assert admin_db.conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id=?", (victim_id,)
            ).fetchone()[0] == 0
            assert admin_db.conn.execute(
                "SELECT COUNT(*) FROM events WHERE session_id IN"
                " (SELECT id FROM sessions WHERE user_id=?)", (victim_id,)
            ).fetchone()[0] == 0
            assert admin_db.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE user_id=? OR assigned_by=?",
                (victim_id, victim_id),
            ).fetchone()[0] == 0
            print("cascade delete     : %s" % removed)

            # delete_session / bulk delete keep the events table consistent.
            keep_id = admin_db.create_session(2)
            admin_db.log_event(keep_id, "focus")
            admin_db.end_session(keep_id, 5, 1)
            gone_id = admin_db.create_session(2)
            admin_db.log_event(gone_id, "away")
            admin_db.end_session(gone_id, 3, 3)
            events_before = admin_db.conn.execute(
                "SELECT COUNT(*) FROM events").fetchone()[0]
            result = admin_db.delete_sessions_by_ids([gone_id])
            assert result == {"events": 1, "sessions": 1}, result
            assert admin_db.conn.execute(
                "SELECT COUNT(*) FROM events").fetchone()[0] == events_before - 1
            assert admin_db.delete_sessions_by_ids([]) == {"events": 0, "sessions": 0}
            print("delete sessions    : single, bulk and empty-list paths OK")

            # clear_completed_tasks / reset_employee_passwords
            task_id = admin_db.add_task(2, "Finished task")
            admin_db.toggle_task(task_id)
            assert admin_db.clear_completed_tasks() == 1
            assert admin_db.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE is_done=1").fetchone()[0] == 0
            changed = admin_db.reset_employee_passwords("9999")
            assert changed >= 1
            assert admin_db.get_user("marwan", "9999", "employee") is not None
            assert admin_db.get_user("manager", "1234", "manager") is not None
            print("password reset     : %d employee row(s) -> '9999' (manager untouched)"
                  % changed)

            counts = admin_db.table_counts()
            assert set(counts) == {"users", "sessions", "events", "tasks"}, counts
            print("table counts       : %s" % counts)

            # factory_reset leaves exactly the two demo accounts.
            cal_ev = admin_db.create_calendar_event("Factory reset probe", "2026-10-27", 1)
            admin_db.set_calendar_attendees(cal_ev, [2])
            probe_chat = admin_db.create_ai_chat(2, "probe")
            admin_db.add_ai_message(probe_chat, "user", "probe")
            assert admin_db.factory_reset() is True
            for table in ("calendar_events", "calendar_attendees", "ai_chats", "ai_messages"):
                assert admin_db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
            counts = admin_db.table_counts()
            assert counts["sessions"] == 0 and counts["events"] == 0, counts
            assert counts["tasks"] == 0, counts
            assert counts["users"] == 2, counts
            names = sorted(u["username"] for u in admin_db.get_all_users())
            assert names == ["manager", "marwan"], names
            assert admin_db.get_user("manager", "1234", "manager") is not None
            assert admin_db.get_user("marwan", "1234", "employee") is not None
            for table, count in counts.items():
                print("  SELECT COUNT(*) FROM %-8s -> %d" % (table, count))
            print("factory reset      : 2 demo users, empty sessions/events/tasks")

            # Export / import round trip.
            export_path = os.path.join(admin_dir, "backup.db")
            admin_db.export_database(export_path)
            assert os.path.exists(export_path)
            check = sqlite3.connect(export_path)
            check.execute("PRAGMA integrity_check").fetchone()
            exported_users = check.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            assert exported_users == 2, exported_users
            check.close()
            print("export database    : copy opens cleanly with %d users" % exported_users)

            admin_db.add_task(2, "Added after the backup")
            assert admin_db.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
            admin_db.import_database(export_path)
            assert admin_db.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
            assert admin_db.table_counts()["users"] == 2
            print("import database    : restored the backup in place")
        finally:
            admin_db.close()

    print("All DatabaseManager tests passed")
