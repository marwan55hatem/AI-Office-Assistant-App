"""A small, durable queue for session data, so a network drop never loses timer data.

Session state (the latest counters) and events are written to a local SQLite file
first and sent to ``POST /sessions/sync`` in batches by :class:`SyncLoop`. The server
treats a batch it has already seen as a no-op, so a batch that was sent but whose
answer was lost is simply sent again. Only timers and event types are stored here:
no passwords, tokens, images or window titles.
"""
import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

COUNTERS = ("focus_seconds", "distraction_seconds", "away_seconds",
            "screen_productive_seconds", "screen_distracted_seconds", "screen_idle_seconds")
MAX_EVENTS_PER_BATCH = 500


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Outbox:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript("""
            -- one row per session until it has ended and the server has its last version
            CREATE TABLE IF NOT EXISTS pending_sessions (
                id TEXT PRIMARY KEY, body TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1, sent_version INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS pending_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
        """)
        self._db.commit()

    # ------------------------------------------------------------------ writes (UI thread)
    def start_session(self, session_id: str, local_date: str) -> None:
        body = {"id": session_id, "local_date": local_date, "started_at": utc_now(),
                **{name: 0 for name in COUNTERS}}
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO pending_sessions (id, body) VALUES (?, ?)",
                             (session_id, json.dumps(body)))
            self._db.commit()

    def update_session(self, session_id: str, *, ended: bool = False, **counters) -> None:
        """Record the newest counters (and, at the end, the end time) of a session."""
        with self._lock:
            row = self._db.execute("SELECT body FROM pending_sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                return                        # unknown session (e.g. started on another PC)
            body = json.loads(row[0])
            for name in COUNTERS:
                if name in counters and counters[name] is not None:
                    body[name] = max(int(body.get(name, 0)), int(counters[name]))
            if ended:
                body["ended_at"] = utc_now()
            self._db.execute("UPDATE pending_sessions SET body=?, version=version+1 WHERE id=?",
                             (json.dumps(body), session_id))
            self._db.commit()

    def add_event(self, session_id: str, event_type: str) -> None:
        body = {"id": str(uuid.uuid4()), "session_id": session_id, "event_type": event_type,
                "occurred_at": utc_now()}
        with self._lock:
            self._db.execute("INSERT INTO pending_events (body) VALUES (?)", (json.dumps(body),))
            self._db.commit()

    # ------------------------------------------------------------------ sending (sync thread)
    def pending(self) -> int:
        with self._lock:
            sessions = self._db.execute(
                "SELECT COUNT(*) FROM pending_sessions WHERE version > sent_version").fetchone()[0]
            events = self._db.execute("SELECT COUNT(*) FROM pending_events").fetchone()[0]
        return sessions + events

    def flush(self, api) -> bool:
        """Send one batch. Returns True when the outbox is empty afterwards.

        Raises the client's ``Offline`` / ``SessionExpired`` / ``ApiError`` so the
        caller knows why nothing was sent; the data stays queued in that case.
        """
        with self._lock:
            sessions = self._db.execute("SELECT id, body, version FROM pending_sessions "
                                        "WHERE version > sent_version").fetchall()
            events = self._db.execute("SELECT seq, body FROM pending_events ORDER BY seq LIMIT ?",
                                      (MAX_EVENTS_PER_BATCH,)).fetchall()
        if not sessions and not events:
            return True
        batch = {"sessions": [json.loads(body) for _id, body, _v in sessions],
                 "events": [json.loads(body) for _seq, body in events]}
        api.post("/sessions/sync", batch)
        with self._lock:
            for session_id, _body, version in sessions:
                self._db.execute("UPDATE pending_sessions SET sent_version=? WHERE id=? AND sent_version < ?",
                                 (version, session_id, version))
            # an ended session whose final version reached the server is done
            for session_id, body in self._db.execute(
                    "SELECT id, body FROM pending_sessions WHERE version = sent_version").fetchall():
                if "ended_at" in json.loads(body):
                    self._db.execute("DELETE FROM pending_sessions WHERE id=?", (session_id,))
            if events:
                self._db.execute("DELETE FROM pending_events WHERE seq <= ?", (events[-1][0],))
            self._db.commit()
            left = self._db.execute(
                "SELECT (SELECT COUNT(*) FROM pending_sessions WHERE version > sent_version) + "
                "(SELECT COUNT(*) FROM pending_events)").fetchone()[0]
        return left == 0

    def close(self) -> None:
        with self._lock:
            self._db.close()


class SyncLoop(threading.Thread):
    """Sends the outbox every few seconds in the background; ``wake()`` sends at once."""

    def __init__(self, outbox: Outbox, api, interval: float = 5.0):
        super().__init__(name="outbox-sync", daemon=True)
        self.outbox = outbox
        self.api = api
        self.interval = interval
        self._wake = threading.Event()
        self._stopping = threading.Event()

    def wake(self) -> None:
        self._wake.set()

    def stop(self, flush: bool = True) -> None:
        self._stopping.set()
        self._wake.set()
        if self.is_alive():
            self.join(timeout=10)
        if flush:
            self._send_all()

    def run(self) -> None:
        while not self._stopping.is_set():
            self._wake.wait(self.interval)
            self._wake.clear()
            if not self._stopping.is_set():
                self._send_all()

    def _send_all(self) -> None:
        from cloud.api import ApiError, Offline, SessionExpired

        if not self.api.signed_in:
            return
        try:
            for _ in range(20):               # a long offline period: catch up in a few batches
                if self.outbox.flush(self.api):
                    break
        except (Offline, SessionExpired):
            pass                              # stays queued; the banner tells the user
        except ApiError as error:
            logger.warning("The server refused session data (%s); it stays queued", error.status)
        except Exception:
            logger.warning("Sending session data failed; it stays queued", exc_info=True)
