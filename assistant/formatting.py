"""Plain-Python text formatting shared by the UI and the chat assistant.

Nothing in here imports Qt, so the assistant engine can be tested (and run)
without any GUI.  ``ui/calendar_screen.py`` re-exports :func:`format_deadline`
and :func:`deadline_state`, so the Tasks table, the To Do list, the tray
notifications and the chat assistant all word a deadline the same way.
"""

from datetime import date, datetime, timedelta

from database.db_manager import deadline_due_datetime

#: A deadline closer than this counts as "soon" (amber).
SOON_HOURS = 24

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fmt_duration(seconds):
    """``7500`` -> ``"2h 05m"``, ``2700`` -> ``"45m"``, ``0`` -> ``"0m"``."""
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return "%dh %02dm" % (hours, minutes)
    return "%dm" % minutes


def _as_date(value):
    """Turn ``'YYYY-MM-DD'`` / ``date`` / ``datetime`` into a ``date`` (or None)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def format_deadline(value, time=None, today=None):
    """Human-readable deadline, the same text everywhere in the app.

    ``value`` is a ``datetime`` (its clock time is used), or a date as
    ``'YYYY-MM-DD'`` / ``date`` with an optional ``time`` string ``'HH:MM'``.

        "Today, 14:00"     the date is today
        "Tomorrow, 14:00"  the date is tomorrow
        "Oct 27, 14:00"    any other day
        "Oct 27"           no time set (due at the end of that day)
    """
    day = _as_date(value)
    if day is None:
        return "—"
    if isinstance(value, datetime) and not time:
        time = value.strftime("%H:%M")

    today = today or date.today()
    if day == today:
        label = "Today"
    elif day == today + timedelta(days=1):
        label = "Tomorrow"
    else:
        label = "%s %d" % (_MONTHS[day.month - 1], day.day)
    return "%s, %s" % (label, str(time)[:5]) if time else label


def deadline_state(deadline_date, deadline_time=None, is_done=False, now=None):
    """Classify a task deadline: ``none`` / ``done`` / ``overdue`` / ``soon`` / ``normal``.

    * ``none``    -- the task has no deadline
    * ``done``    -- it has one but the task is finished (always shown muted)
    * ``overdue`` -- the deadline has passed
    * ``soon``    -- due within :data:`SOON_HOURS`
    * ``normal``  -- further away
    """
    due = deadline_due_datetime(deadline_date, deadline_time)
    if due is None:
        return "none"
    if is_done:
        return "done"
    now = now or datetime.now()
    if due < now:
        return "overdue"
    if due <= now + timedelta(hours=SOON_HOURS):
        return "soon"
    return "normal"
