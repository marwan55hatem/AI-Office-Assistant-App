"""Narrow, domain-specific views of the database (Interface Segregation).

``DatabaseManager`` has ~80 public methods.  A class that only stores chat messages
should not be able to -- or have to know it can -- delete users.  Each *repository*
below exposes only the methods of one domain and forwards them to the shared
connection of the ``DatabaseManager`` (so there is still one connection, one
transaction model and one schema).

The old API keeps working: ``db.get_user(...)`` is the same call as
``db.users.get_user(...)``.  New code should depend on the smallest repository it
needs (``db.chats``, ``db.knowledge``...); older code can migrate one class at a time.
``tests/test_repositories.py`` checks that every public ``DatabaseManager`` method
belongs to exactly one repository, so a new method cannot be forgotten.
"""

from typing import Tuple


class _Repository:
    """Forwards only the names listed in ``METHODS`` to the owning ``DatabaseManager``."""

    METHODS: Tuple[str, ...] = ()

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        if name in type(self).METHODS:
            return getattr(self._db, name)
        raise AttributeError(
            "%s has no method %r (it belongs to another repository, or does not exist)"
            % (type(self).__name__, name))

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(type(self).METHODS))


class UserRepo(_Repository):
    """Accounts: login, profile, sign-up approval, administration."""

    METHODS = (
        "get_user", "get_user_by_id", "get_all_employees", "get_all_users", "get_user_status",
        "update_user_profile", "update_user_password", "update_user",
        "create_signup_request", "get_pending_users", "approve_user", "reject_user",
        "delete_user_cascade", "reset_employee_passwords",
        "username_taken", "create_user", "count_user_related_rows",
    )


class SessionRepo(_Repository):
    """Work sessions and the reports computed from them."""

    METHODS = (
        "create_session", "end_session", "get_today_sessions", "get_all_sessions_today",
        "get_sessions_history", "get_weekly_report", "get_weekly_report_all",
        "get_today_totals", "get_today_totals_per_user", "get_active_session_count_today",
        "get_active_employees_today", "get_employee_status_today",
        "get_absent_employees", "get_high_distraction_employees",
        "get_session", "delete_session", "delete_sessions_by_ids", "delete_sessions_filtered",
    )


class ActivityRepo(_Repository):
    """The focus / distraction / away events logged during sessions."""

    METHODS = ("log_event", "get_last_event", "get_recent_events", "get_session_events",
               "get_all_events", "delete_event")


class TaskRepo(_Repository):
    """To-do tasks, manager assignments and deadlines."""

    METHODS = (
        "get_tasks", "get_assigned_tasks", "get_self_tasks", "get_all_tasks",
        "add_task", "toggle_task", "delete_task", "clear_completed_tasks",
        "update_task_deadline", "get_upcoming_deadlines", "delete_all_tasks",
    )


class CalendarRepo(_Repository):
    """Calendar events and their attendees."""

    METHODS = (
        "create_calendar_event", "update_calendar_event", "delete_calendar_event",
        "get_calendar_event", "get_calendar_events_for_user", "get_calendar_events_on_date",
        "get_today_events", "get_calendar_attendees", "set_calendar_attendees",
    )


class ChatRepo(_Repository):
    """AI Chat conversations and their messages."""

    METHODS = (
        "create_ai_chat", "get_ai_chats", "get_ai_chat", "update_ai_chat_title", "delete_ai_chat",
        "add_ai_message", "get_ai_messages", "count_ai_messages",
    )


class KnowledgeRepo(_Repository):
    """The manager's documents for the assistant (RAG)."""

    METHODS = (
        "upsert_knowledge_doc", "get_knowledge_docs", "get_knowledge_doc",
        "delete_knowledge_doc", "set_knowledge_visibility", "knowledge_signature",
    )


class AdminRepo(_Repository):
    """Whole-database operations used by the admin panel."""

    METHODS = ("export_database", "import_database", "factory_reset", "table_counts")


#: attribute name on ``DatabaseManager`` -> repository class
REPOSITORIES = {
    "users": UserRepo,
    "sessions": SessionRepo,
    "activity": ActivityRepo,
    "tasks": TaskRepo,
    "calendar": CalendarRepo,
    "chats": ChatRepo,
    "knowledge": KnowledgeRepo,
    "admin": AdminRepo,
}
