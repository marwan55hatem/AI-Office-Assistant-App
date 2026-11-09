"""``RemoteDatabase``: the online stand-in for :class:`database.db_manager.DatabaseManager`.

It offers the same methods with the same return shapes (dicts with the same keys,
local ``YYYY-MM-DD`` / ``HH:MM`` strings), so the screens do not need to know whether
their data comes from the local SQLite file or from the server. Ids are the server's
UUID strings.

Session data goes through the :class:`~cloud.outbox.Outbox`, so a session keeps
recording while offline. Everything else needs the server: when it cannot be reached,
reads return an empty result and writes report "No connection", and the window shows
its offline banner.
"""
import logging
import os
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from cloud.api import ApiError, Offline, SessionExpired
from cloud.outbox import Outbox, SyncLoop
from database.repositories import REPOSITORIES

logger = logging.getLogger(__name__)

NO_CONNECTION = "No connection to the server. Please try again when you are online."
_UNSET = object()
#: server account status -> the words the screens already use
_STATUS = {"active": "approved", "pending": "pending", "disabled": "rejected"}


# ---------------------------------------------------------------- conversions
def _local_dt(value):
    if not value:
        return None
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment.astimezone() if moment.tzinfo else moment


def _stamp(value):
    """Server time -> local ``YYYY-MM-DD HH:MM:SS`` (what SQLite stored)."""
    moment = _local_dt(value)
    return moment.strftime("%Y-%m-%d %H:%M:%S") if moment else None


def _hhmm(value):
    return str(value)[:5] if value else None


def _today() -> str:
    return date.today().isoformat()


def _days_ago(days: int) -> str:
    return (date.today() - timedelta(days=max(int(days), 1) - 1)).isoformat()


def _iso(value) -> str:
    """A time-zone-aware datetime (or an ISO string) as ISO-8601 with its offset."""
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.astimezone()                    # a naive time is this computer's local time
    return value.isoformat()


def _user(row):
    if row is None:
        return None
    return {"id": row["id"], "username": row["email"], "email": row["email"], "full_name": row["full_name"],
            "role": row["role"], "status": _STATUS.get(row["status"], row["status"])}


def _task(row):
    return {"id": row["id"], "user_id": row["user_id"], "assigned_by": row["assigned_by"], "title": row["title"],
            "description": row["description"], "priority": row["priority"], "is_done": 1 if row["is_done"] else 0,
            "deadline_date": row["deadline_date"], "deadline_time": _hhmm(row["deadline_time"]),
            "created_at": _stamp(row["created_at"])}


def _session(row):
    start, end = _local_dt(row["started_at"]), _local_dt(row["ended_at"])
    return {"id": row["id"], "user_id": row["user_id"], "full_name": row["full_name"], "date": row["local_date"],
            "start_time": start.strftime("%H:%M:%S") if start else None,
            "end_time": end.strftime("%H:%M:%S") if end else None,
            "focus_seconds": row["focus_seconds"], "distraction_seconds": row["distraction_seconds"],
            "away_seconds": row["away_seconds"], "distractions": 0,
            "screen_productive_seconds": row["screen_productive_seconds"],
            "screen_distracted_seconds": row["screen_distracted_seconds"],
            "screen_idle_seconds": row["screen_idle_seconds"]}


def _event(row):
    return {"id": row["id"], "session_id": row["session_id"], "event_type": row["event_type"],
            "timestamp": _stamp(row["occurred_at"])}


def _calendar_event(row):
    event = {"id": row["id"], "title": row["title"], "description": row["description"],
             "event_date": row["event_date"], "start_time": _hhmm(row["start_time"]),
             "end_time": _hhmm(row["end_time"]), "created_by": row["created_by"],
             "created_by_name": row["created_by_name"], "created_at": _stamp(row["created_at"]),
             "attendee_count": row["attendee_count"]}
    if row.get("attendees") is not None:
        event["attendees"] = [{"id": a["id"], "username": a["email"], "full_name": a["full_name"]}
                              for a in row["attendees"]]
    return event


def _chat(row):
    return {"id": row["id"], "user_id": row["user_id"], "title": row["title"],
            "created_at": _stamp(row["created_at"]), "updated_at": _stamp(row["updated_at"]),
            "message_count": row.get("message_count", 0), "last_message": row.get("last_message")}


def _message(row):
    return {"id": row["id"], "chat_id": row["chat_id"], "role": row["role"], "content": row["content"],
            "source": row["source"], "created_at": _stamp(row["created_at"])}


def _document(row):
    doc = {k: row[k] for k in ("id", "filename", "visibility", "uploaded_by", "size", "words")}
    doc["created_at"], doc["updated_at"] = _stamp(row["created_at"]), _stamp(row["updated_at"])
    if row.get("content") is not None:
        doc["content"] = row["content"]
    return doc


# ---------------------------------------------------------------- error handling
def reads(default):
    """A read that returns ``default`` when the server cannot be reached or refuses."""
    def decorate(method):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            try:
                return method(self, *args, **kwargs)
            except (Offline, SessionExpired):
                return default() if callable(default) else default
            except ApiError as error:
                if error.status not in (403, 404):
                    logger.warning("%s failed: %s", method.__name__, error.status)
                return default() if callable(default) else default
        return wrapper
    return decorate


def writes(failure):
    """A write whose failure is reported as the screens expect (``(False, msg)``, None...)."""
    def decorate(method):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            try:
                return method(self, *args, **kwargs)
            except (Offline, SessionExpired):
                return failure(NO_CONNECTION)
            except ApiError as error:
                if error.status >= 500:
                    logger.warning("%s failed: %s", method.__name__, error.status)
                return failure(str(error))
        return wrapper
    return decorate


def _pair(message):
    return False, message


def _none(_message):
    return None


def _false(_message):
    return False


class RemoteDatabase:
    """Same interface as ``DatabaseManager``, backed by the Office Assistant API."""

    #: the sign-in e-mail is managed by the company, not edited in Settings
    can_change_username = False

    def __init__(self, api, outbox_path: str | None = None, sync_interval: float = 5.0, start_sync=True):
        self.api = api
        if outbox_path is None:
            from app_paths import USER_DATA_DIR
            os.makedirs(USER_DATA_DIR, exist_ok=True)
            outbox_path = os.path.join(USER_DATA_DIR, "outbox.db")
        self.outbox = Outbox(outbox_path)
        self.sync = SyncLoop(self.outbox, api, sync_interval)
        if start_sync:
            self.sync.start()
        for name, repository in REPOSITORIES.items():
            setattr(self, name, repository(self))
        from cloud.reports_api import ReportsApi

        self.reports = ReportsApi(api)          # manager reports with charts (online only)

    # ------------------------------------------------------------------ account
    @property
    def me(self):
        return _user(self.api.me["user"]) if self.api.me else None

    def sign_in(self, identifier, password, remember=True):
        """``(user, None)`` on success, ``(None, message)`` otherwise."""
        try:
            self.api.login(identifier, password, remember)
        except Offline:
            return None, NO_CONNECTION
        except ApiError as error:
            return None, str(error)
        self.sync.wake()
        return self.me, None

    def restore_sign_in(self):
        """The remembered user, signed in again, or None."""
        try:
            me = self.api.restore()
        except (Offline, ApiError):
            return None
        return _user(me["user"]) if me else None

    def sign_out(self):
        self.sync.wake()
        self.api.logout()

    def join(self, full_name, email, password, company_code=None, invite_token=None):
        try:
            return True, self.api.join(full_name, email, password, company_code=company_code,
                                       invite_token=invite_token)
        except Offline:
            return False, NO_CONNECTION
        except ApiError as error:
            return False, str(error)

    @writes(_pair)
    def change_password(self, user_id, current_password, new_password):
        self.api.change_password(current_password, new_password)
        return True, "Password updated"

    # ------------------------------------------------------------------ users
    def get_user(self, username, password, role):
        """Not used online (sign-in goes through :meth:`sign_in`)."""
        return None

    @reads(None)
    def get_user_by_id(self, user_id):
        if self.api.me and str(user_id) == self.api.me["user"]["id"]:
            return self.me
        return _user(self.api.get(f"/users/{user_id}"))

    @reads(list)
    def get_all_employees(self):
        return [_user(u) for u in self.api.get("/users", role="employee")]

    @writes(_pair)
    def update_user_profile(self, user_id, *, full_name=None, username=None):
        if username is not None and username != (self.me or {}).get("username"):
            return False, "Your e-mail address is your sign-in and cannot be changed here"
        if full_name is None:
            return False, "Nothing to update"
        if not str(full_name).strip():
            return False, "Full name cannot be empty"
        self.api.patch("/users/me", {"full_name": str(full_name).strip()})
        self.api.load_me()
        return True, "Profile updated"

    def email_preferences(self):
        """``{"email_notifications": bool, "language": "en"|"ar"}`` of the signed-in user, or None."""
        user = (self.api.me or {}).get("user")
        if not user:
            return None
        return {"email_notifications": bool(user.get("email_notifications", True)),
                "language": user.get("language") or "en"}

    @writes(_pair)
    def set_email_preferences(self, *, email_notifications=None, language=None):
        """Optional (meeting) e-mails on/off and the e-mail language; urgent tasks are always e-mailed."""
        body = {}
        if email_notifications is not None:
            body["email_notifications"] = bool(email_notifications)
        if language is not None:
            if language not in ("en", "ar"):
                return False, "Unknown language"
            body["language"] = language
        if not body:
            return False, "Nothing to update"
        self.api.patch("/users/me/preferences", body)
        self.api.load_me()
        return True, "E-mail settings saved"

    def update_user_password(self, user_id, new_password):
        return False, "Enter your current password to change it"

    def create_signup_request(self, username, password, full_name):
        return False, "Use a company code or an invite link to join"

    @reads(list)
    def get_pending_users(self):
        return [_user(u) for u in self.api.get("/users", status="pending", role="employee")]

    @writes(_none)
    def approve_user(self, user_id):
        self.api.post(f"/users/{user_id}/approve")

    @writes(_none)
    def reject_user(self, user_id):
        self.api.patch(f"/users/{user_id}/status", {"status": "disabled"})

    def get_user_status(self, username, role):
        return None

    # ------------------------------------------------------------------ sessions
    def create_session(self, user_id):
        """Start a session locally; it reaches the server through the outbox."""
        session_id = str(uuid.uuid4())
        self.outbox.start_session(session_id, _today())
        self.sync.wake()
        return session_id

    def update_session_progress(self, session_id, focus_seconds, away_seconds, *, distraction_seconds=0,
                                screen_productive=0, screen_distracted=0, screen_idle=0, apps=None):
        self.outbox.update_session(session_id, apps=apps, focus_seconds=focus_seconds, away_seconds=away_seconds,
                                   distraction_seconds=distraction_seconds,
                                   screen_productive_seconds=screen_productive,
                                   screen_distracted_seconds=screen_distracted, screen_idle_seconds=screen_idle)

    def end_session(self, session_id, focus_seconds, away_seconds, *, distraction_seconds=0,
                    screen_productive=0, screen_distracted=0, screen_idle=0, apps=None):
        self.outbox.update_session(session_id, ended=True, apps=apps, focus_seconds=focus_seconds,
                                   away_seconds=away_seconds,
                                   distraction_seconds=distraction_seconds,
                                   screen_productive_seconds=screen_productive,
                                   screen_distracted_seconds=screen_distracted, screen_idle_seconds=screen_idle)
        self.sync.wake()

    def log_event(self, session_id, event_type):
        self.outbox.add_event(session_id, event_type)

    @reads(list)
    def get_today_sessions(self, user_id):
        return [_session(s) for s in self.api.get("/sessions", user_id=user_id, since=_today(), until=_today())]

    @reads(list)
    def get_all_sessions_today(self):
        rows = [_session(s) for s in self.api.get("/sessions", since=_today(), until=_today())]
        for row in rows:
            row["username"] = None
        return rows

    @reads(list)
    def get_sessions_history(self, user_id=None, days=7):
        since = None if days and int(days) >= 3650 else _days_ago(days or 1)
        return [_session(s) for s in self.api.get("/sessions", user_id=user_id, since=since)]

    @reads(None)
    def get_session(self, session_id):
        return _session(self.api.get(f"/sessions/{session_id}"))

    @reads(list)
    def get_session_events(self, session_id):
        return [_event(e) for e in self.api.get(f"/sessions/{session_id}/events")]

    @reads(None)
    def get_last_event(self, session_id):
        events = self.get_session_events(session_id)
        return events[-1] if events else None

    def _range(self, days, user_id=None):
        return self.api.get("/stats/range", start=_days_ago(days), end=_today(), user_id=user_id)

    @reads(lambda: {"total_focus": 0, "total_away": 0, "total_distraction": 0, "total_sessions": 0})
    def get_weekly_report(self, user_id):
        rows = self._range(7, user_id)
        row = rows[0] if rows else {}
        return {key: row.get(key, 0) for key in ("total_focus", "total_away", "total_distraction", "total_sessions")}

    @reads(list)
    def get_weekly_report_all(self):
        return [dict(row) for row in self._range(7)]

    @reads(list)
    def get_absent_employees(self, days=3):
        return [{"id": r["id"], "full_name": r["full_name"]} for r in self._range(days) if r["total_sessions"] == 0]

    def _today_stats(self):
        return self.api.get("/stats/today", day=_today())

    @reads(lambda: {"focus_seconds": 0, "distraction_seconds": 0, "away_seconds": 0})
    def get_today_totals(self):
        return dict(self._today_stats()["totals"])

    @reads(0)
    def get_active_session_count_today(self):
        return self._today_stats()["running_sessions"]

    @reads(list)
    def get_today_totals_per_user(self):
        return [{"id": e["id"], "full_name": e["full_name"], "focus_seconds": e["focus_seconds"],
                 "distraction_seconds": e["distraction_seconds"], "away_seconds": e["away_seconds"]}
                for e in self._today_stats()["employees"]]

    @reads(list)
    def get_employee_status_today(self):
        rows = []
        for e in self._today_stats()["employees"]:
            if e["sessions"] == 0:
                status = "absent"
            elif e["running"] and e["last_event_type"] == "distraction":
                status = "distracted"
            else:
                status = "present"
            rows.append({"id": e["id"], "full_name": e["full_name"], "status": status,
                         "focus_seconds": e["focus_seconds"], "distraction_seconds": e["distraction_seconds"],
                         "away_seconds": e["away_seconds"]})
        return rows

    @reads(list)
    def get_active_employees_today(self):
        return [{"id": e["id"], "full_name": e["full_name"]} for e in self._today_stats()["employees"] if e["running"]]

    @reads(list)
    def get_high_distraction_employees(self, threshold_seconds=3600):
        rows = [{"id": e["id"], "full_name": e["full_name"], "distraction_seconds": e["distraction_seconds"]}
                for e in self._today_stats()["employees"]
                if e["sessions"] and e["distraction_seconds"] >= int(threshold_seconds)]
        return sorted(rows, key=lambda r: -r["distraction_seconds"])

    @reads(list)
    def get_recent_events(self, limit=10):
        return [{**_event(e), "full_name": e["full_name"]} for e in self.api.get("/events/recent", limit=int(limit))]

    # ------------------------------------------------------------------ tasks
    def _tasks(self, user_id, kind):
        return [_task(t) for t in self.api.get("/tasks", user_id=user_id, kind=kind)]

    @reads(list)
    def get_tasks(self, user_id):
        return self._tasks(user_id, "all")

    @reads(list)
    def get_assigned_tasks(self, user_id):
        return self._tasks(user_id, "assigned")

    @reads(list)
    def get_self_tasks(self, user_id):
        return self._tasks(user_id, "self")

    @writes(_none)
    def add_task(self, user_id, title, priority="normal", assigned_by=None, description=None,
                 deadline_date=None, deadline_time=None):
        body = {"user_id": user_id, "title": title, "priority": priority, "description": description,
                "deadline_date": deadline_date, "deadline_time": deadline_time if deadline_date else None}
        return self.api.post("/tasks", body)["id"]

    @writes(_pair)
    def update_task_deadline(self, task_id, deadline_date, deadline_time=None):
        self.api.patch(f"/tasks/{task_id}/deadline", {"deadline_date": deadline_date,
                                                      "deadline_time": deadline_time if deadline_date else None})
        return True, "Deadline updated"

    @reads(list)
    def get_upcoming_deadlines(self, user_id, within_hours=24):
        from assistant.formatting import deadline_due_datetime

        now = datetime.now()
        horizon = now + timedelta(hours=within_hours)
        upcoming = []
        for task in self.get_tasks(user_id):
            if task["is_done"] or not task["deadline_date"]:
                continue
            due = deadline_due_datetime(task["deadline_date"], task["deadline_time"])
            if due is None or due > horizon:
                continue
            task["overdue"] = due < now
            task["due_at"] = due.strftime("%Y-%m-%d %H:%M")
            upcoming.append((due, task))
        upcoming.sort(key=lambda pair: pair[0])
        return [task for _due, task in upcoming]

    @writes(_none)
    def toggle_task(self, task_id):
        self.api.post(f"/tasks/{task_id}/toggle")

    @writes(_none)
    def delete_task(self, task_id):
        self.api.delete(f"/tasks/{task_id}")

    # ------------------------------------------------------------------ meeting requests (Phase 6)
    @reads(list)
    def get_meeting_requests(self, status=None):
        """Your requests (employee) or the company's (manager), newest change first.
        ``status``: pending / accepted / declined / rescheduled / cancelled / open."""
        return self.api.get("/meeting-requests", status=status)

    @reads(0)
    def count_meeting_requests_waiting(self):
        """Requests waiting for you: pending ones for a manager, rescheduled ones for an employee."""
        return int(self.api.get("/meeting-requests/waiting-count").get("waiting", 0))

    @writes(_pair)
    def request_meeting(self, topic, proposed_times, note=None, duration_minutes=30):
        """``proposed_times``: 1-3 time-zone-aware datetimes (or ISO strings with an offset)."""
        row = self.api.post("/meeting-requests", {"topic": topic, "note": note or None,
                                                  "proposed_times": [_iso(t) for t in proposed_times],
                                                  "duration_minutes": duration_minutes})
        return True, row

    @writes(_pair)
    def accept_meeting_request(self, request_id, time, duration_minutes=None):
        body = {"time": _iso(time)}
        if duration_minutes:
            body["duration_minutes"] = duration_minutes
        return True, self.api.post(f"/meeting-requests/{request_id}/accept", body)

    @writes(_pair)
    def decline_meeting_request(self, request_id, reason):
        return True, self.api.post(f"/meeting-requests/{request_id}/decline", {"reason": reason})

    @writes(_pair)
    def reschedule_meeting_request(self, request_id, proposed_times, note=None):
        return True, self.api.post(f"/meeting-requests/{request_id}/reschedule",
                                   {"proposed_times": [_iso(t) for t in proposed_times], "note": note or None})

    @writes(_pair)
    def cancel_meeting_request(self, request_id, reason=None):
        return True, self.api.post(f"/meeting-requests/{request_id}/cancel", {"reason": reason or None})

    # ------------------------------------------------------------------ chat with the manager (Phase 7)
    @reads(list)
    def get_chat_conversations(self):
        """Managers: every employee's conversation (news first). Employees: their own one."""
        return self.api.get("/chat/conversations")

    @reads(None)
    def get_chat_messages(self, employee_id, before_id=None, after_id=None, limit=50):
        """``{"messages": [...oldest first], "has_more": bool}`` or None when offline."""
        return self.api.get(f"/chat/{employee_id}/messages", before_id=before_id, after_id=after_id, limit=limit)

    @writes(_pair)
    def send_chat_message(self, employee_id, body):
        return True, self.api.post(f"/chat/{employee_id}/messages", {"body": body})

    @writes(_false)
    def mark_chat_read(self, employee_id, up_to_id):
        self.api.post(f"/chat/{employee_id}/read", {"up_to_id": int(up_to_id)})
        return True

    @reads(0)
    def count_unread_chat(self):
        return int(self.api.get("/chat/unread-count").get("unread", 0))

    # ------------------------------------------------------------------ in-app notifications
    @reads(list)
    def get_notifications(self, unread_only=False, limit=50):
        return self.api.get("/notifications", unread=unread_only or None, limit=limit)

    @writes(_false)
    def mark_notification_read(self, notification_id):
        self.api.post(f"/notifications/{notification_id}/read")
        return True

    @writes(_false)
    def mark_all_notifications_read(self):
        self.api.post("/notifications/read-all")
        return True

    # ------------------------------------------------------------------ calendar
    @writes(_none)
    def create_calendar_event(self, title, event_date, created_by, description=None, start_time=None, end_time=None):
        body = {"title": title, "event_date": event_date, "description": description,
                "start_time": start_time, "end_time": end_time}
        return self.api.post("/calendar", body)["id"]

    @writes(_pair)
    def update_calendar_event(self, event_id, *, title=_UNSET, description=_UNSET, event_date=_UNSET,
                              start_time=_UNSET, end_time=_UNSET):
        fields = {"title": title, "description": description, "event_date": event_date,
                  "start_time": start_time, "end_time": end_time}
        changes = {k: v for k, v in fields.items() if v is not _UNSET}
        if not changes:
            return False, "Nothing to update"
        if "title" in changes and (changes["title"] is None or not str(changes["title"]).strip()):
            return False, "Title cannot be empty"
        self.api.patch(f"/calendar/{event_id}", changes)
        return True, "Event updated"

    @writes(_pair)
    def delete_calendar_event(self, event_id):
        self.api.delete(f"/calendar/{event_id}")
        return True, "Event deleted"

    @reads(list)
    def get_calendar_attendees(self, event_id):
        return self.get_calendar_event(event_id)["attendees"]

    @reads(None)
    def get_calendar_event(self, event_id):
        return _calendar_event(self.api.get(f"/calendar/{event_id}"))

    @writes(_pair)
    def set_calendar_attendees(self, event_id, user_ids):
        saved = self.api.put(f"/calendar/{event_id}/attendees", {"user_ids": [str(u) for u in user_ids]})
        return True, "%d attendee(s) saved" % len(saved)

    @reads(list)
    def get_calendar_events_for_user(self, user_id, from_date=None, to_date=None):
        return [_calendar_event(e) for e in self.api.get("/calendar", start=from_date, end=to_date)]

    @reads(list)
    def get_calendar_events_on_date(self, date_str, user_id=None):
        return [_calendar_event(e) for e in self.api.get("/calendar", start=date_str, end=date_str)]

    def get_today_events(self, user_id):
        return self.get_calendar_events_on_date(_today(), user_id)

    # ------------------------------------------------------------------ AI chats
    @writes(_none)
    def create_ai_chat(self, user_id, title=None):
        return self.api.post("/ai/chats", {"title": title})["id"]

    @reads(list)
    def get_ai_chats(self, user_id):
        return [_chat(c) for c in self.api.get("/ai/chats")]

    @reads(None)
    def get_ai_chat(self, chat_id):
        chat = _chat(self.api.get(f"/ai/chats/{chat_id}"))
        return {k: chat[k] for k in ("id", "user_id", "title", "created_at", "updated_at")}

    @writes(_pair)
    def update_ai_chat_title(self, chat_id, title):
        self.api.patch(f"/ai/chats/{chat_id}", {"title": title})
        return True, "Title updated"

    @writes(_pair)
    def delete_ai_chat(self, chat_id):
        self.api.delete(f"/ai/chats/{chat_id}")
        return True, "Chat deleted"

    @writes(_none)
    def add_ai_message(self, chat_id, role, content, source=None):
        if role not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        return self.api.post(f"/ai/chats/{chat_id}/messages", {"role": role, "content": content,
                                                               "source": source})["id"]

    @reads(list)
    def get_ai_messages(self, chat_id, limit=None):
        return [_message(m) for m in self.api.get(f"/ai/chats/{chat_id}/messages", limit=limit or None)]

    def count_ai_messages(self, chat_id):
        return len(self.get_ai_messages(chat_id))

    # ------------------------------------------------------------------ knowledge
    def upsert_knowledge_doc(self, filename, content, visibility="everyone", uploaded_by=None):
        if visibility not in ("everyone", "managers"):
            raise ValueError("visibility must be 'everyone' or 'managers'")
        if not str(filename).strip():
            raise ValueError("filename is required")
        try:
            row = self.api.put("/documents", {"filename": str(filename).strip(), "content": content,
                                              "visibility": visibility})
        except (Offline, SessionExpired):
            raise ValueError(NO_CONNECTION) from None
        except ApiError as error:
            raise ValueError(str(error)) from None
        return row["id"], bool(row["created"])

    @reads(list)
    def get_knowledge_docs(self, include_manager_only=True, with_content=False):
        return [_document(d) for d in self.api.get("/documents", with_content=with_content or None,
                                                   include_managers=include_manager_only)]

    @reads(None)
    def get_knowledge_doc(self, doc_id):
        return _document(self.api.get(f"/documents/{doc_id}"))

    @writes(_false)
    def delete_knowledge_doc(self, doc_id):
        self.api.delete(f"/documents/{doc_id}")
        return True

    @writes(_false)
    def set_knowledge_visibility(self, doc_id, visibility):
        if visibility not in ("everyone", "managers"):
            raise ValueError("visibility must be 'everyone' or 'managers'")
        self.api.patch(f"/documents/{doc_id}", {"visibility": visibility})
        return True

    def knowledge_signature(self, include_manager_only=True):
        return tuple((d["id"], d["size"], d["updated_at"])
                     for d in sorted(self.get_knowledge_docs(include_manager_only), key=lambda d: d["id"]))

    # ------------------------------------------------------------------ shutdown
    def close(self):
        """Send whatever is still queued, then stop the background sender."""
        self.sync.stop(flush=True)
        self.outbox.close()
