"""System-tray notifications for today's calendar events and task deadlines.

:class:`TrayNotifier` lives for the whole application (it is a child of the root
window).  It starts when somebody logs in, checks the database every minute and
shows each event / deadline **once per session**; it stops again on logout.  If
the system has no tray, the application keeps working -- the sidebar badge is the
fallback.
"""

import logging
from datetime import datetime

from PyQt5.QtCore import QObject, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QSystemTrayIcon

from ui import theme
from ui.calendar_event_dialog import describe_event_time
from assistant.formatting import format_deadline

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 60000     # how often the database is checked
STAGGER_MS = 5000             # gap between several notifications at once
SHOW_MS = 8000                # how long a notification stays visible
DEADLINE_WINDOW_HOURS = 24


def make_tray_icon():
    """Draw the tray icon in code: an accent rounded square with a calendar glyph."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(theme.ACCENT))
    painter.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), 14, 14)

    white = QColor("#FFFFFF")
    # calendar page
    painter.setBrush(white)
    painter.drawRoundedRect(QRectF(14, 20, 36, 30), 5, 5)
    # header band + the two binder rings
    painter.setBrush(QColor(theme.ACCENT_PRESS))
    painter.drawRect(QRectF(14, 20, 36, 9))
    painter.setBrush(white)
    painter.drawRoundedRect(QRectF(21, 13, 5, 12), 2, 2)
    painter.drawRoundedRect(QRectF(38, 13, 5, 12), 2, 2)
    # day dots
    painter.setBrush(QColor(theme.ACCENT))
    for column in range(3):
        for row in range(2):
            painter.drawEllipse(QRectF(19 + column * 10, 33 + row * 8, 5, 5))
    painter.end()
    return QIcon(pixmap)


class TrayNotifier(QObject):
    """Shows today's events and due / overdue tasks as tray notifications."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.user_id = None
        #: keys already shown this session, e.g. ``("task", 7, "overdue")``
        self.notified = set()
        #: every notification actually sent, as ``(title, message)`` (for tests)
        self.sent = []
        self._queue = []
        self._flushing = False

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(make_tray_icon(), self)
            self.tray.setToolTip("Desktop AI Office Assistant")
            self.tray.show()

        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self.check)

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #
    def start(self, user):
        """Begin watching for ``user`` (a dict with ``id``); clears the session memory."""
        self.stop()
        user_id = (user or {}).get("id")
        if user_id is None or self.db is None:
            return
        self.user_id = user_id
        self.check()                      # login counts as "app start"
        self.timer.start()

    def stop(self):
        """Stop watching (logout): nothing runs while nobody is signed in."""
        self.timer.stop()
        self.user_id = None
        self.notified.clear()
        self._queue.clear()

    def shutdown(self):
        """Stop and remove the tray icon (called when the application quits)."""
        self.stop()
        if self.tray is not None:
            self.tray.hide()

    # ------------------------------------------------------------------ #
    #  Checking
    # ------------------------------------------------------------------ #
    @staticmethod
    def _event_is_over(event, now):
        """True when today's event has already ended (nothing left to announce).

        An event with no end time counts as over once its start time has passed;
        an all-day event never is.
        """
        finish = event.get("end_time") or event.get("start_time")
        if not finish:
            return False
        try:
            clock = datetime.strptime(finish, "%H:%M")
        except ValueError:
            return False
        return now.replace(hour=clock.hour, minute=clock.minute, second=0,
                           microsecond=0) < now

    def check(self):
        """Queue a notification for everything new; returns the new ``(title, message)`` list."""
        if self.user_id is None or self.db is None:
            return []

        now = datetime.now()
        fresh = []
        try:
            events = self.db.get_today_events(self.user_id)
            deadlines = self.db.get_upcoming_deadlines(
                self.user_id, DEADLINE_WINDOW_HOURS
            )
        except Exception:
            logger.warning("check failed", exc_info=True)
            return []

        for event in events:
            key = ("event", event["id"], "today")
            if key in self.notified or self._event_is_over(event, now):
                continue
            self.notified.add(key)
            fresh.append(("Today: " + event["title"], describe_event_time(event)))

        for task in deadlines:
            when = format_deadline(task["deadline_date"], task.get("deadline_time"))
            if task["overdue"]:
                key = ("task", task["id"], "overdue")
                title, message = "Overdue: " + task["title"], "Was due " + when
            else:
                key = ("task", task["id"], "due")
                title, message = "Task due soon: " + task["title"], "Due " + when
            if key in self.notified:
                continue
            self.notified.add(key)
            fresh.append((title, message))

        self._queue.extend(fresh)
        self._flush()
        return fresh

    # ------------------------------------------------------------------ #
    #  Showing
    # ------------------------------------------------------------------ #
    def _flush(self):
        """Show the next queued notification; the rest follow a few seconds apart
        (a new toast replaces the previous one, so they must not overlap)."""
        if self._flushing or not self._queue:
            return
        title, message = self._queue.pop(0)
        self.show_notification(title, message)
        if self._queue:
            self._flushing = True
            QTimer.singleShot(STAGGER_MS, self._flush_next)

    def _flush_next(self):
        self._flushing = False
        if self.user_id is not None:
            self._flush()

    def show_notification(self, title, message):
        """Send one notification to the tray (recorded in :attr:`sent` either way)."""
        self.sent.append((title, message))
        if self.tray is not None:
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, SHOW_MS)
