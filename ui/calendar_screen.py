"""Calendar screen and the shared deadline helpers.

* :class:`CalendarScreen` -- month grid with event dots, "Today" and "Upcoming"
  lists.  Managers can create and edit their events; everybody else gets a
  read-only view.
* :func:`format_deadline` / :func:`deadline_state` -- shared by the manager Tasks
  table, the employee To Do list and the tray notifications so every deadline
  reads the same way everywhere.
"""

import logging
from datetime import date, timedelta

from PyQt5.QtCore import QDate, QPointF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPen, QTextCharFormat
from PyQt5.QtWidgets import (
    QCalendarWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from assistant.formatting import format_deadline
from ui import theme
from ui.widgets import clear_layout

logger = logging.getLogger(__name__)

def style_calendar_widget(calendar):
    """Make a ``QCalendarWidget`` (or a ``QDateEdit`` popup) match the theme.

    Style sheets cannot recolour the weekday header or the weekend columns and
    the month arrows come from the platform style (bright green), so those bits
    are set here from the active palette.  Call it again after a theme switch.
    """
    calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
    calendar.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
    calendar.setGridVisible(False)

    header = QTextCharFormat()
    header.setForeground(QColor(theme.TEXT_MUTED))
    calendar.setHeaderTextFormat(header)

    plain = QTextCharFormat()
    plain.setForeground(QColor(theme.TEXT_PRIMARY))
    for day in (Qt.Monday, Qt.Tuesday, Qt.Wednesday, Qt.Thursday, Qt.Friday):
        calendar.setWeekdayTextFormat(day, plain)
    weekend = QTextCharFormat()
    weekend.setForeground(QColor(theme.TEXT_SECONDARY))
    calendar.setWeekdayTextFormat(Qt.Saturday, weekend)
    calendar.setWeekdayTextFormat(Qt.Sunday, weekend)

    for name, glyph in (("qt_calendar_prevmonth", "\u2039"),
                        ("qt_calendar_nextmonth", "\u203A")):
        button = calendar.findChild(QToolButton, name)
        if button is not None:
            button.setIcon(QIcon())
            button.setText(glyph)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
    return calendar


# --------------------------------------------------------------------------- #
#  Calendar screen
# --------------------------------------------------------------------------- #
_FULL_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
             "Sunday")

UPCOMING_DAYS = 30


class EventCalendar(QCalendarWidget):
    """Month grid that paints a small accent dot under every day with an event.

    The widget's own navigation bar is hidden: the screen has its own header.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._event_days = set()           # {'YYYY-MM-DD'}
        self.setNavigationBarVisible(False)
        self.setGridVisible(False)
        self.setSelectionMode(QCalendarWidget.SingleSelection)
        self.setMinimumHeight(340)
        style_calendar_widget(self)

    def set_event_days(self, days):
        """Replace the set of days that carry an event dot."""
        self._event_days = set(days)
        self.updateCells()

    def has_events(self, day):
        """True when ``day`` (a ``QDate``) has at least one event."""
        return day.toString("yyyy-MM-dd") in self._event_days

    def paintCell(self, painter, rect, day):
        """Default cell, plus a ring on today and a dot on days with events."""
        super().paintCell(painter, rect, day)
        selected = day == self.selectedDate()
        painter.save()
        painter.setRenderHint(painter.Antialiasing, True)
        if day == QDate.currentDate() and not selected:
            painter.setPen(QPen(QColor(theme.ACCENT), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(4, 4, -4, -4), 8, 8)
        if self.has_events(day):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.ON_ACCENT if selected else theme.ACCENT))
            painter.drawEllipse(QPointF(rect.center().x(), rect.bottom() - 9), 3, 3)
        painter.restore()


class EventRow(QFrame):
    """One clickable event line; emits ``clicked(event_id)``."""

    clicked = pyqtSignal(int)

    def __init__(self, event, show_date=False, show_attendees=None, parent=None):
        super().__init__(parent)
        self.event_id = event["id"]
        self.setObjectName("EventRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(56)

        from ui.calendar_event_dialog import describe_event_time

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SP_4, theme.SP_3, theme.SP_4, theme.SP_3)
        outer.setSpacing(theme.SP_1)

        top = QHBoxLayout()
        top.setSpacing(theme.SP_3)

        when = describe_event_time(event)
        if show_date:
            when = "%s  \u00b7  %s" % (format_deadline(event["event_date"]), when)
        time_label = QLabel(when)
        time_label.setObjectName("MutedLabel")
        top.addWidget(time_label)

        title = QLabel(event["title"])
        title.setObjectName("TaskTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)

        if show_date:
            count = QLabel("\U0001F465 %d" % event.get("attendee_count", 0))
            count.setObjectName("MutedLabel")
            top.addWidget(count)
        outer.addLayout(top)

        if event.get("description"):
            note = QLabel(event["description"])
            note.setObjectName("MutedLabel")
            note.setWordWrap(True)
            outer.addWidget(note)
        if show_attendees:
            names = [a["full_name"] for a in show_attendees]
            text = ", ".join(names[:4]) + (" +%d more" % (len(names) - 4) if len(names) > 4 else "")
            who = QLabel("With: " + text)
            who.setObjectName("MutedLabel")
            who.setWordWrap(True)
            outer.addWidget(who)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.event_id)
        super().mousePressEvent(event)


class CalendarScreen(QWidget):
    """Month grid + today + upcoming. Read-only unless the user is a manager."""

    #: Emitted after an event was created, edited or deleted from this screen.
    changed = pyqtSignal()

    REFRESH_MS = 60000

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": 1, "full_name": "Admin Manager", "role": "manager"}
        self.db = db
        self.is_manager = self._detect_manager()

        self._build_ui()
        self.refresh()

        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start()

    def _detect_manager(self):
        role = self.user.get("role")
        if role is None and self.db is not None and self.user.get("id") is not None:
            try:
                row = self.db.get_user_by_id(self.user["id"])
                role = row["role"] if row else None
            except Exception:
                role = None
        return role == "manager"

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("ScrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        body.setSpacing(theme.SP_5)

        grid_card = self._card()
        self.calendar = EventCalendar()
        self.calendar.currentPageChanged.connect(self._update_month_label)
        self.calendar.activated.connect(self._on_day_activated)
        grid_card.layout().addWidget(self.calendar)
        body.addWidget(grid_card, 3)

        lists = QHBoxLayout()
        lists.setSpacing(theme.SP_5)
        self.today_title = QLabel("")
        self.today_title.setObjectName("H3")
        self.today_box = QVBoxLayout()
        self.today_box.setSpacing(theme.SP_2)
        lists.addWidget(self._list_card(self.today_title, self.today_box), 1)

        upcoming_title = QLabel("Upcoming (next %d days)" % UPCOMING_DAYS)
        upcoming_title.setObjectName("H3")
        self.upcoming_box = QVBoxLayout()
        self.upcoming_box.setSpacing(theme.SP_2)
        lists.addWidget(self._list_card(upcoming_title, self.upcoming_box), 1)
        body.addLayout(lists)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self._update_month_label(self.calendar.yearShown(), self.calendar.monthShown())

    def _build_header(self):
        header = QFrame()
        header.setObjectName("Navbar")
        header.setFixedHeight(theme.NAVBAR_HEIGHT)

        row = QHBoxLayout(header)
        row.setContentsMargins(theme.SP_6, 0, theme.SP_6, 0)
        row.setSpacing(theme.SP_2)

        title = QLabel("\U0001F4C5  Calendar")
        title.setObjectName("H3")
        row.addWidget(title)
        row.addStretch(1)

        self.prev_button = QPushButton("\u2039")
        self.prev_button.setObjectName("IconButton")
        self.prev_button.setToolTip("Previous month")
        self.prev_button.setCursor(Qt.PointingHandCursor)
        self.prev_button.setStyleSheet("font-size: 28px; font-weight: 700;")
        self.prev_button.clicked.connect(lambda: self.calendar.showPreviousMonth())
        row.addWidget(self.prev_button)

        self.month_label = QLabel("")
        self.month_label.setObjectName("H3")
        self.month_label.setAlignment(Qt.AlignCenter)
        self.month_label.setMinimumWidth(190)
        row.addWidget(self.month_label)

        self.next_button = QPushButton("\u203A")
        self.next_button.setObjectName("IconButton")
        self.next_button.setToolTip("Next month")
        self.next_button.setCursor(Qt.PointingHandCursor)
        self.next_button.setStyleSheet("font-size: 28px; font-weight: 700;")
        self.next_button.clicked.connect(lambda: self.calendar.showNextMonth())
        row.addWidget(self.next_button)

        self.new_event_button = None
        if self.is_manager:
            row.addSpacing(theme.SP_4)
            self.new_event_button = QPushButton("+  New Event")
            self.new_event_button.setObjectName("PrimaryButton")
            self.new_event_button.setCursor(Qt.PointingHandCursor)
            # keep the button inside the 76 px header (the global rule is 54 px)
            self.new_event_button.setStyleSheet("min-height: 0px;")
            self.new_event_button.setFixedHeight(48)
            self.new_event_button.clicked.connect(self._on_new_event)
            row.addWidget(self.new_event_button, 0, Qt.AlignVCenter)
        return header

    @staticmethod
    def _card():
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_4, theme.SP_4, theme.SP_4, theme.SP_4)
        layout.setSpacing(theme.SP_3)
        return card

    def _list_card(self, title_label, box_layout):
        card = self._card()
        card.layout().addWidget(title_label)
        card.layout().addLayout(box_layout)
        card.layout().addStretch(1)
        return card

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def _update_month_label(self, year, month):
        self.month_label.setText("%s %d" % (_FULL_MONTHS[month - 1], year))

    def _auto_refresh(self):
        """Timer slot: only reload while the page is actually on screen."""
        if self.isVisible():
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        """Reload the event dots, the Today list and the Upcoming list."""
        # the weekday header / weekend colours are set in code, so follow a theme switch
        style_calendar_widget(self.calendar)
        today = date.today()
        self.today_title.setText(
            "Today \u2014 %s, %s %d" % (_WEEKDAYS[today.weekday()],
                                       _FULL_MONTHS[today.month - 1], today.day)
        )
        clear_layout(self.today_box)
        clear_layout(self.upcoming_box)
        if self.db is None or self.user.get("id") is None:
            return

        user_id = self.user["id"]
        try:
            everything = self.db.get_calendar_events_for_user(user_id)
            todays = self.db.get_today_events(user_id)
            upcoming = self.db.get_calendar_events_for_user(
                user_id,
                from_date=(today + timedelta(days=1)).strftime("%Y-%m-%d"),
                to_date=(today + timedelta(days=UPCOMING_DAYS)).strftime("%Y-%m-%d"),
            )
        except Exception:
            logger.warning("refresh failed", exc_info=True)
            return

        self.calendar.set_event_days(event["event_date"] for event in everything)

        if todays:
            for event in todays:
                attendees = self.db.get_calendar_attendees(event["id"])
                self._add_row(self.today_box, event, show_attendees=attendees)
        else:
            self._add_empty(self.today_box, "No events today.")

        if upcoming:
            for event in upcoming:
                self._add_row(self.upcoming_box, event, show_date=True)
        else:
            self._add_empty(self.upcoming_box, "No upcoming events.")

    def _add_row(self, layout, event, show_date=False, show_attendees=None):
        row = EventRow(event, show_date=show_date, show_attendees=show_attendees)
        row.clicked.connect(self._open_event)
        layout.addWidget(row)

    @staticmethod
    def _add_empty(layout, text):
        label = QLabel(text)
        label.setObjectName("EmptyLabel")
        layout.addWidget(label)

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _on_new_event(self, default_date=None):
        """Open the create dialog (managers only)."""
        if not self.is_manager:
            return
        from ui.calendar_event_dialog import CalendarEventDialog

        dialog = CalendarEventDialog(
            self.db, self.user["id"], parent=self,
            default_date=default_date if isinstance(default_date, QDate) else None,
        )
        dialog.saved.connect(self._on_saved)
        dialog.exec_()

    def _on_day_activated(self, day):
        """Double-clicking a day starts a new event on that date (managers)."""
        if self.is_manager:
            self._on_new_event(day)

    def _open_event(self, event_id):
        """Creator -> edit dialog; anybody else -> read-only details."""
        from ui.calendar_event_dialog import CalendarEventDetailDialog, CalendarEventDialog

        event = self.db.get_calendar_event(event_id) if self.db else None
        if event is None:
            self.refresh()
            return
        if self.is_manager and event["created_by"] == self.user["id"]:
            dialog = CalendarEventDialog(self.db, self.user["id"], event_id, parent=self)
            dialog.saved.connect(self._on_saved)
        else:
            dialog = CalendarEventDetailDialog(self.db, event_id, parent=self)
        dialog.exec_()

    def _on_saved(self):
        self.refresh()
        self.changed.emit()
