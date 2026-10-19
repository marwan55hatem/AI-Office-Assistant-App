"""Manager workspace: collapsible sidebar + page stack.

The module is organised as a shell (:class:`ManagerScreen`) that owns the
sidebar and a ``QStackedWidget``, plus one page per sidebar entry.  Pages and
the shell between them keep every database call and method signature that the
rest of the application relied on before the sidebar refactor.
"""

import logging
from PyQt5.QtCore import QDate, QTime, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from assistant.formatting import deadline_state, format_deadline
from ui.calendar_screen import CalendarScreen, style_calendar_widget
from ui.shell import ShellNavigationMixin
from ui.sidebar import Sidebar

logger = logging.getLogger(__name__)

_fmt_hms = theme.fmt_hms


STATUS_STYLES = {
    "present": ("\U0001F7E2  Present", theme.SUCCESS),
    "distracted": ("\U0001F7E1  Distracted", theme.WARNING),
    "absent": ("\U0001F534  Absent", theme.DANGER),
}

TABLE_HEADERS = ["NAME", "TODAY'S STATUS", "FOCUS TIME", "DISTRACTED TIME", "AWAY TIME"]

PENDING_HEADERS = ["FULL NAME", "USERNAME", "REQUESTED", "ACTIONS"]

HISTORY_HEADERS = ["DATE", "USER", "START", "END", "FOCUS", "DISTRACTED", "AWAY", ""]

TASK_HEADERS = ["EMPLOYEE", "TASK", "PRIORITY", "DEADLINE", "STATUS"]

WEEKLY_HEADERS = [
    "EMPLOYEE",
    "TOTAL FOCUS",
    "TOTAL DISTRACTED",
    "TOTAL AWAY",
    "SESSIONS",
]

HISTORY_RANGES = [("Today", 1), ("Last 7 days", 7), ("Last 30 days", 30),
                  ("All time", 3650)]

TABLE_ROW_HEIGHT = theme.TABLE_ROW_HEIGHT

SESSION_DETAIL_SIZE = (760, 600)
EVENT_ROW_HEIGHT = 48
#: Colour (a name in ``ui.theme``) of each event type in the session log.
EVENT_COLOUR_NAMES = {"focus": "SUCCESS", "away": "DANGER", "distraction": "WARNING"}

MANAGER_ITEMS = [
    ("item", "home", "\U0001F3E0", "Home"),
    ("item", "calendar", "\U0001F4C5", "Calendar"),
    ("item", "employees", "🧑", "Employees"),
    ("item", "sessions", "\U0001F552", "Sessions"),
    ("item", "tasks", "\u2705", "Tasks"),
    ("item", "reports", "\U0001F4CA", "Reports"),
    ("item", "ai_helper", "\U0001F916", "AI Helper"),
    ("item", "ai_chat", "\U0001F4AC", "AI Chat"),
    ("item", "knowledge", "\U0001F4DA", "Knowledge"),
    ("item", "todo", "\U0001F4CB", "To Do"),
    ("item", "settings", "⚙️", "Settings"),
    ("separator",),
]


class _Page(QWidget):
    """Shared plumbing for the manager pages (db, user, card helper)."""

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": 1, "full_name": "Admin Manager"}
        self.db = db
        self.employees = []

    def refresh(self):
        """Reload this page from the database. Overridden where needed."""

    @staticmethod
    def _card(title_text, trailing=None, subtitle=None):
        """Bordered, shadowed section card; returns ``(card, content_layout)``."""
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_3)

        header_row = QHBoxLayout()
        header_row.setSpacing(theme.SP_3)

        title = QLabel(title_text)
        title.setObjectName("H3")
        header_row.addWidget(title, 0)
        header_row.addStretch(1)

        for widget in (trailing or []):
            header_row.addWidget(widget)
        layout.addLayout(header_row)

        if subtitle is not None:
            hint = QLabel(subtitle)
            hint.setObjectName("MutedLabel")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        return card, layout

    @staticmethod
    def _page_scroll(content):
        """Wrap a page body in the standard scrolling container."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll


class EmployeeStatusPage(_Page):
    """Pending signup requests + today's employee status table."""

    employees_changed = pyqtSignal()

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(user=user, db=db, parent=parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QWidget()
        content.setObjectName("ScrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        body.setSpacing(theme.SP_5)

        body.addWidget(self._build_pending_card())
        body.addWidget(self._build_status_card(), 1)
        root.addWidget(self._page_scroll(content), 1)

        self.refresh()

    def refresh(self):
        """Reload the employee cards and the pending sign-ups."""
        if self.db is None:
            return
        try:
            self.employees = self.db.get_employee_status_today()
        except Exception:
            logger.warning("status reload failed", exc_info=True)
            self.employees = []
        self._refresh_table()
        self._reload_pending()

    def _build_pending_card(self):
        self.pending_count_pill = QLabel("0 waiting")
        self.pending_count_pill.setObjectName("PillBadge")
        self.pending_count_pill.setAlignment(Qt.AlignCenter)

        card, layout = self._card(
            "🔔  Pending Signup Requests", trailing=[self.pending_count_pill]
        )

        self.pending_table = QTableWidget(0, len(PENDING_HEADERS))
        self.pending_table.setHorizontalHeaderLabels(PENDING_HEADERS)
        self.pending_table.verticalHeader().setVisible(False)
        self.pending_table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        self.pending_table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        self.pending_table.setShowGrid(False)
        self.pending_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.pending_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pending_table.setFocusPolicy(Qt.NoFocus)
        self.pending_table.setMinimumHeight(190)
        self.pending_table.setWordWrap(False)

        pending_header_view = self.pending_table.horizontalHeader()
        pending_header_view.setHighlightSections(False)
        pending_header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        pending_header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        pending_header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        pending_header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        layout.addWidget(self.pending_table)
        return card


    def _build_status_card(self):
        refresh_pill = QLabel("🔄 refreshes every 30s")
        refresh_pill.setObjectName("PillMuted")
        refresh_pill.setAlignment(Qt.AlignCenter)

        card, layout = self._card(
            "🧑  Employee Status — Today", trailing=[refresh_pill]
        )

        self.table = QTableWidget(0, len(TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        self.table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setMinimumHeight(300)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)

        header_view = self.table.horizontalHeader()
        header_view.setHighlightSections(False)
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(TABLE_HEADERS)):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeToContents)

        layout.addWidget(self.table, 1)
        return card


    def _refresh_table(self):
        self.table.setRowCount(0)
        # The "No employees yet." state merges all columns; drop the span or a
        # later real row would render inside the merged cell.
        self.table.clearSpans()

        if not self.employees:
            self.table.setRowCount(1)
            self.table.setRowHeight(0, TABLE_ROW_HEIGHT)
            item = QTableWidgetItem("No employees yet.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, len(TABLE_HEADERS))
            return

        for employee in self.employees:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setRowHeight(row, TABLE_ROW_HEIGHT)

            name_item = QTableWidgetItem(f"🧑  {employee['full_name']}")
            self.table.setItem(row, 0, name_item)

            # Status is a coloured pill rather than coloured text.
            status_text, status_color = STATUS_STYLES.get(
                employee["status"], ("⚪  Unknown", theme.TEXT_MUTED)
            )
            pill = QLabel(status_text)
            pill.setObjectName(
                {
                    "present": "PillPresent",
                    "distracted": "PillDistracted",
                    "absent": "PillAbsent",
                }.get(employee["status"], "PillMuted")
            )
            pill.setAlignment(Qt.AlignCenter)
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(theme.SP_2, 0, theme.SP_2, 0)
            holder_layout.addWidget(pill)
            self.table.setCellWidget(row, 1, holder)

            focus_item = QTableWidgetItem(_fmt_hms(employee["focus_seconds"]))
            self.table.setItem(row, 2, focus_item)

            # Three durations, no counts: focus / distracted / away.
            distraction_item = QTableWidgetItem(
                _fmt_hms(employee["distraction_seconds"])
            )
            distraction_item.setForeground(QColor(theme.WARNING))
            self.table.setItem(row, 3, distraction_item)

            away_item = QTableWidgetItem(_fmt_hms(employee["away_seconds"]))
            away_item.setForeground(QColor(theme.TEXT_MUTED))
            self.table.setItem(row, 4, away_item)


    def _reload_pending(self):
        """Refresh the pending-signup table from the database."""
        try:
            rows = self.db.get_pending_users() if self.db else []
        except Exception:
            rows = []

        self.pending_table.setRowCount(0)
        # A previous "no pending requests" state merged the four columns with a
        # span; drop it or the real rows would render inside the merged cell.
        self.pending_table.clearSpans()

        for user in rows:
            row = self.pending_table.rowCount()
            self.pending_table.insertRow(row)
            self.pending_table.setItem(
                row, 0, QTableWidgetItem(user["full_name"])
            )
            self.pending_table.setItem(row, 1, QTableWidgetItem(user["username"]))
            self.pending_table.setItem(row, 2, QTableWidgetItem("—"))
            self.pending_table.setRowHeight(row, TABLE_ROW_HEIGHT)

            holder = QWidget()
            actions = QHBoxLayout(holder)
            actions.setContentsMargins(theme.SP_2, 0, theme.SP_2, 0)
            actions.setSpacing(theme.SP_2)

            approve = QPushButton("Approve")
            approve.setStyleSheet(theme.row_button_qss(success=True))
            approve.setFixedHeight(theme.ROW_BUTTON_HEIGHT)
            approve.setMinimumWidth(approve.sizeHint().width() + 16)
            approve.setCursor(Qt.PointingHandCursor)
            approve.clicked.connect(
                lambda _, uid=user["id"]: self._approve(uid)
            )

            reject = QPushButton("Reject")
            reject.setStyleSheet(theme.row_button_qss(danger=True))
            reject.setFixedHeight(theme.ROW_BUTTON_HEIGHT)
            reject.setMinimumWidth(reject.sizeHint().width() + 16)
            reject.setCursor(Qt.PointingHandCursor)
            reject.clicked.connect(lambda _, uid=user["id"]: self._reject(uid))

            actions.addWidget(approve)
            actions.addWidget(reject)
            actions.addStretch(1)
            self.pending_table.setCellWidget(row, 3, holder)

        if not rows:
            self.pending_table.setRowCount(1)
            self.pending_table.setRowHeight(0, TABLE_ROW_HEIGHT)
            item = QTableWidgetItem("No pending requests.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            self.pending_table.setItem(0, 0, item)
            self.pending_table.setSpan(0, 0, 1, len(PENDING_HEADERS))

        if hasattr(self, "pending_count_pill"):
            count = len(rows)
            self.pending_count_pill.setText(
                "0 waiting" if not count else ("1 waiting" if count == 1
                                               else f"{count} waiting")
            )

        # Approving or rejecting changes who can be assigned a task.
        self.employees_changed.emit()


    def _approve(self, user_id):
        try:
            self.db.approve_user(user_id)
            QMessageBox.information(
                self, "Approved", "The user can now log in."
            )
        except Exception as error:
            QMessageBox.critical(self, "Error", str(error))
        self._reload_pending()


    def _reject(self, user_id):
        try:
            self.db.reject_user(user_id)
            QMessageBox.information(
                self, "Rejected", "The user's request was rejected."
            )
        except Exception as error:
            QMessageBox.critical(self, "Error", str(error))
        self._reload_pending()




class SessionsHistoryPage(_Page):
    """Filterable session history with a per-session detail dialog."""

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(user=user, db=db, parent=parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QWidget()
        content.setObjectName("ScrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        body.setSpacing(theme.SP_5)
        body.addWidget(self._build_history_section(), 1)
        root.addWidget(self._page_scroll(content), 1)

        self.refresh()

    def refresh(self):
        """Reload the user filter and the history table."""
        self._reload_user_filter()
        self._reload_history()

    def _build_history_section(self):
        """Card with the filter row + sessions table."""
        header = QLabel("📅  Sessions History — last 7 days")
        header.setObjectName("H3")
        header.setWordWrap(True)
        self.history_header = header

        self.history_user = QComboBox()
        self.history_user.setMinimumWidth(170)
        self.history_user.addItem("All users", None)
        self.history_user.currentIndexChanged.connect(self._reload_history)

        self.history_range = QComboBox()
        self.history_range.setMinimumWidth(150)
        for label, days in HISTORY_RANGES:
            self.history_range.addItem(label, days)
        self.history_range.setCurrentIndex(1)          # "Last 7 days"
        self.history_range.currentIndexChanged.connect(self._reload_history)

        refresh = QPushButton("🔄  Refresh")
        refresh.setObjectName("GhostButton")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setToolTip("Reload the dashboard from the database")
        refresh.clicked.connect(self.refresh)

        # The card helper puts the title and the trailing widgets in one row; the
        # title is swapped for the filter row below so everything stays aligned.
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)

        section = QVBoxLayout(card)
        section.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        section.setSpacing(theme.SP_3)

        header_row = QHBoxLayout()
        header_row.setSpacing(theme.SP_3)
        header_row.addWidget(header)
        header_row.addStretch(1)
        header_row.addWidget(self.history_user)
        header_row.addWidget(self.history_range)
        header_row.addWidget(refresh)
        section.addLayout(header_row)

        self.history_table = QTableWidget(0, len(HISTORY_HEADERS))
        self.history_table.setHorizontalHeaderLabels(HISTORY_HEADERS)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        self.history_table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        self.history_table.setShowGrid(False)
        self.history_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setFocusPolicy(Qt.NoFocus)
        self.history_table.setMinimumHeight(360)
        self.history_table.setMaximumHeight(16777215)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setWordWrap(False)

        history_header_view = self.history_table.horizontalHeader()
        history_header_view.setHighlightSections(False)
        for column in range(len(HISTORY_HEADERS) - 1):
            history_header_view.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        history_header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        history_header_view.setMinimumSectionSize(110)
        history_header_view.setSectionResizeMode(
            len(HISTORY_HEADERS) - 1, QHeaderView.Fixed
        )
        self.history_table.setColumnWidth(len(HISTORY_HEADERS) - 1, 120)

        section.addWidget(self.history_table, 1)
        return card


    def _reload_user_filter(self):
        """Keep the history user filter in step with the employee list."""
        current = self.history_user.currentData()
        self.history_user.blockSignals(True)
        self.history_user.clear()
        self.history_user.addItem("All users", None)
        for employee in self.employees:
            self.history_user.addItem(employee["full_name"], employee["id"])
        index = self.history_user.findData(current)
        self.history_user.setCurrentIndex(index if index >= 0 else 0)
        self.history_user.blockSignals(False)


    def _reload_history(self):
        """Reload the sessions-history table for the selected filters."""
        if self.db is None:
            return

        days = self.history_range.currentData() or 7
        # The heading must describe what is on screen, not a fixed range.
        self.history_header.setText(
            f"📅   Sessions History — {self.history_range.currentText().lower()}"
        )
        user_id = self.history_user.currentData()
        if user_id is not None:
            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                user_id = None

        try:
            rows = self.db.get_sessions_history(user_id=user_id, days=days)
        except Exception:
            logger.warning("history reload failed", exc_info=True)
            rows = []

        self.history_table.setRowCount(0)
        self.history_table.clearSpans()

        if not rows:
            self.history_table.setRowCount(1)
            self.history_table.setRowHeight(0, TABLE_ROW_HEIGHT)
            item = QTableWidgetItem("No sessions yet.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            self.history_table.setItem(0, 0, item)
            self.history_table.setSpan(0, 0, 1, len(HISTORY_HEADERS))
            return

        for session in rows:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self.history_table.setRowHeight(row, TABLE_ROW_HEIGHT)

            values = [
                (session["date"], theme.TEXT_PRIMARY),
                (session["full_name"], theme.TEXT_PRIMARY),
                (session["start_time"] or "—", theme.TEXT_MUTED),
                (session["end_time"] or "active",
                 theme.WARNING if session["end_time"] is None else theme.TEXT_MUTED),
                (_fmt_hms(session["focus_seconds"]), theme.SUCCESS),
                (_fmt_hms(session["distraction_seconds"]), theme.WARNING),
                (_fmt_hms(session["away_seconds"]), theme.DANGER),
            ]
            for column, (text, color) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(color))
                self.history_table.setItem(row, column, item)

            detail = QPushButton("View")
            detail.setStyleSheet(theme.row_button_qss())
            detail.setFixedSize(84, theme.ROW_BUTTON_HEIGHT)
            detail.setCursor(Qt.PointingHandCursor)
            detail.setToolTip("Show this session's events")
            detail.clicked.connect(
                lambda _, sid=session["id"]: self._open_session_detail(sid)
            )
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(theme.SP_1, 0, theme.SP_1, 0)
            holder_layout.addWidget(detail)
            self.history_table.setCellWidget(row, len(HISTORY_HEADERS) - 1, holder)


    def _open_session_detail(self, session_id):
        """Modal dialog with one session's numbers and its event log."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Session details")
        dialog.resize(*SESSION_DETAIL_SIZE)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_3)

        session, events = self._load_session_detail(session_id)
        layout.addWidget(self._session_summary_label(session))

        events_label = QLabel("Events")
        events_label.setObjectName("SectionHeader")
        layout.addWidget(events_label)
        layout.addWidget(self._build_events_table(events), 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec_()

    def _load_session_detail(self, session_id):
        """``(session, events)`` for the dialog; ``(None, [])`` after telling the user why."""
        try:
            return self.db.get_session(session_id), self.db.get_session_events(session_id)
        except Exception as error:
            logger.warning("session detail failed", exc_info=True)
            QMessageBox.warning(self, "Session details", f"Could not load data: {error}")
            return None, []

    @staticmethod
    def _session_summary_label(session):
        """The key numbers of a session as one aligned block of text."""
        if session is None:
            missing = QLabel("Session not found.")
            missing.setObjectName("ErrorLabel")
            return missing
        rows = [
            ("Date", session["date"]),
            ("User", session.get("full_name", "—")),
            ("Start", session["start_time"] or "—"),
            ("End", session["end_time"] or "active"),
            ("Focus", _fmt_hms(session["focus_seconds"])),
            ("Distracted", _fmt_hms(session.get("distraction_seconds"))),
            ("Away", _fmt_hms(session["away_seconds"])),
            ("Screen productive", _fmt_hms(session.get("screen_productive_seconds"))),
            ("Screen distracted", _fmt_hms(session.get("screen_distracted_seconds"))),
            ("Screen idle", _fmt_hms(session.get("screen_idle_seconds"))),
        ]
        label = QLabel("\n".join("%-20s%s" % (name + ":", value) for name, value in rows))
        label.setObjectName("MutedLabel")
        return label

    @staticmethod
    def _build_events_table(events):
        """A read-only table of a session's focus / distraction / away events."""
        table = QTableWidget(len(events), 3)
        table.setHorizontalHeaderLabels(["#", "EVENT", "TIMESTAMP"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        table.setShowGrid(False)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setFocusPolicy(Qt.NoFocus)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        for row, event in enumerate(events):
            table.setRowHeight(row, EVENT_ROW_HEIGHT)
            table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            colour_name = EVENT_COLOUR_NAMES.get(event["event_type"], "TEXT_MUTED")
            event_item = QTableWidgetItem(event["event_type"])
            event_item.setForeground(QColor(getattr(theme, colour_name)))
            table.setItem(row, 1, event_item)
            table.setItem(row, 2, QTableWidgetItem(event["timestamp"] or ""))

        if not events:
            table.setRowCount(1)
            item = QTableWidgetItem("No events recorded for this session.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            table.setItem(0, 0, item)
            table.setSpan(0, 0, 1, 3)
        return table




class TasksPage(_Page):
    """Assign a task to one employee, plus every task currently stored."""

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(user=user, db=db, parent=parent)
        self.assign_priority = "normal"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QWidget()
        content.setObjectName("ScrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        body.setSpacing(theme.SP_5)
        body.addWidget(self._build_assign_card())
        body.addWidget(self._build_tasks_card(), 1)
        root.addWidget(self._page_scroll(content), 1)

        self.refresh()

    def _build_tasks_card(self):
        card, layout = self._card("\U0001F5C2  All Tasks")

        self.tasks_table = QTableWidget(0, len(TASK_HEADERS))
        self.tasks_table.setHorizontalHeaderLabels(TASK_HEADERS)
        self.tasks_table.verticalHeader().setVisible(False)
        self.tasks_table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        self.tasks_table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        self.tasks_table.setShowGrid(False)
        self.tasks_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.tasks_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tasks_table.setFocusPolicy(Qt.NoFocus)
        self.tasks_table.setMinimumHeight(300)
        self.tasks_table.setAlternatingRowColors(True)
        self.tasks_table.setWordWrap(False)

        header = self.tasks_table.horizontalHeader()
        header.setHighlightSections(False)
        # Cell widgets (the pills) are not measured by ResizeToContents, so the
        # pill columns get explicit widths instead of clipping their labels.
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.tasks_table.setColumnWidth(0, 210)
        self.tasks_table.setColumnWidth(2, 130)
        self.tasks_table.setColumnWidth(3, 175)
        self.tasks_table.setColumnWidth(4, 120)

        layout.addWidget(self.tasks_table, 1)
        return card

    def _all_tasks(self):
        """Every task in the database, with the owner's name."""
        rows = []
        if self.db is None:
            return rows
        try:
            for employee in self.db.get_all_employees():
                for task in self.db.get_tasks(employee["id"]):
                    rows.append((employee["full_name"], task))
        except Exception:
            logger.warning("task list failed", exc_info=True)
        rows.sort(key=lambda row: (bool(row[1].get("is_done")),
                                   str(row[1].get("priority")) != "urgent",
                                   row[0]))
        return rows

    def _refresh_tasks(self):
        rows = self._all_tasks()
        self.tasks_table.setRowCount(0)
        self.tasks_table.clearSpans()

        if not rows:
            self.tasks_table.setRowCount(1)
            self.tasks_table.setRowHeight(0, TABLE_ROW_HEIGHT)
            item = QTableWidgetItem("No tasks yet.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            self.tasks_table.setItem(0, 0, item)
            self.tasks_table.setSpan(0, 0, 1, len(TASK_HEADERS))
            return

        for full_name, task in rows:
            row = self.tasks_table.rowCount()
            self.tasks_table.insertRow(row)
            self.tasks_table.setRowHeight(row, TABLE_ROW_HEIGHT)

            name_item = QTableWidgetItem(f"🧑  {full_name}")
            self.tasks_table.setItem(row, 0, name_item)

            title_item = QTableWidgetItem(str(task.get("title", "")))
            title_item.setForeground(
                QColor(theme.TEXT_MUTED if task.get("is_done") else theme.TEXT_PRIMARY)
            )
            self.tasks_table.setItem(row, 1, title_item)

            description = (task.get("description") or "").strip()
            if description:
                # Two lines: the title, then the description in a small muted font
                # (the full text is also the tooltip).
                title_item.setText("")
                holder = QWidget()
                holder.setToolTip(description)
                column = QVBoxLayout(holder)
                column.setContentsMargins(16, 0, 8, 0)
                column.setSpacing(2)
                column.setAlignment(Qt.AlignVCenter)

                title_label = QLabel(str(task.get("title", "")))
                title_label.setObjectName("TaskTitle")
                title_label.setProperty(
                    "done", "true" if task.get("is_done") else "false"
                )
                column.addWidget(title_label)

                description_label = QLabel(description.replace("\n", " "))
                description_label.setObjectName("MutedLabel")
                column.addWidget(description_label)

                self.tasks_table.setCellWidget(row, 1, holder)
                self.tasks_table.setRowHeight(row, TABLE_ROW_HEIGHT + 16)

            urgent = str(task.get("priority")) == "urgent"
            pill = QLabel("URGENT" if urgent else "Normal")
            pill.setObjectName("PillUrgent" if urgent else "PillMuted")
            pill.setAlignment(Qt.AlignCenter)
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(theme.SP_2, 0, theme.SP_2, 0)
            holder_layout.addWidget(pill)
            self.tasks_table.setCellWidget(row, 2, holder)

            # Deadline: red when overdue, amber within 24 h, muted otherwise
            # (and always muted once the task is done).
            state = deadline_state(
                task.get("deadline_date"), task.get("deadline_time"),
                bool(task.get("is_done")),
            )
            if state == "none":
                deadline_item = QTableWidgetItem("\u2014")
            else:
                deadline_item = QTableWidgetItem(
                    format_deadline(task["deadline_date"], task.get("deadline_time"))
                )
            deadline_item.setForeground(QColor({
                "overdue": theme.DANGER,
                "soon": theme.WARNING,
            }.get(state, theme.TEXT_MUTED)))
            self.tasks_table.setItem(row, 3, deadline_item)

            done = bool(task.get("is_done"))
            status = QLabel("\u2713 Done" if done else "Open")
            status.setObjectName("PillDone" if done else "PillMuted")
            status.setAlignment(Qt.AlignCenter)
            status_holder = QWidget()
            status_layout = QHBoxLayout(status_holder)
            status_layout.setContentsMargins(theme.SP_2, 0, theme.SP_2, 0)
            status_layout.addWidget(status)
            self.tasks_table.setCellWidget(row, 4, status_holder)

    def refresh(self):
        """Reload the task list and the assignee choices."""
        if self.db is not None:
            try:
                self.employees = self.db.get_employee_status_today()
            except Exception:
                self.employees = []
        self._reload_assign_combo()
        self._refresh_tasks()
        # the popup calendar keeps its own colours: re-apply after a theme switch
        style_calendar_widget(self.deadline_date.calendarWidget())

    def _build_assign_card(self):
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_3)

        title = QLabel("📌   Assign Task")
        title.setObjectName("H3")
        layout.addWidget(title)

        self.assign_employee = QComboBox()
        self._reload_assign_combo()
        layout.addWidget(self.assign_employee)

        self.assign_title = QLineEdit()
        self.assign_title.setPlaceholderText("Task title...")
        self.assign_title.setMinimumHeight(theme.FIELD_HEIGHT)
        self.assign_title.returnPressed.connect(self._on_assign)
        layout.addWidget(self.assign_title)

        self.assign_description = QPlainTextEdit()
        self.assign_description.setObjectName("TaskDescriptionInput")
        self.assign_description.setPlaceholderText("Description (optional)…")
        self.assign_description.setMinimumHeight(90)
        # the global input rule sets min-height: 24px, which would win over the line above
        self.assign_description.setStyleSheet("min-height: 90px;")
        layout.addWidget(self.assign_description)

        priority_row = QHBoxLayout()
        priority_row.setSpacing(theme.SP_2)

        self.priority_group = QButtonGroup(self)
        self.priority_group.setExclusive(True)

        self.normal_button = QPushButton("Normal")
        self.normal_button.setObjectName("SegmentButton")
        self.normal_button.setCheckable(True)
        self.normal_button.setChecked(True)
        self.normal_button.setCursor(Qt.PointingHandCursor)

        self.urgent_button = QPushButton("Urgent")
        self.urgent_button.setObjectName("SegmentButton")
        self.urgent_button.setCheckable(True)
        self.urgent_button.setCursor(Qt.PointingHandCursor)

        self.priority_group.addButton(self.normal_button)
        self.priority_group.addButton(self.urgent_button)

        self.normal_button.clicked.connect(lambda: self._set_priority("normal"))
        self.urgent_button.clicked.connect(lambda: self._set_priority("urgent"))

        self.normal_button.setMinimumWidth(140)
        self.urgent_button.setMinimumWidth(140)
        priority_row.addWidget(self.normal_button)
        priority_row.addWidget(self.urgent_button)
        priority_row.addStretch(1)
        layout.addLayout(priority_row)

        # Optional deadline: nothing is stored unless the box is ticked.
        deadline_row = QHBoxLayout()
        deadline_row.setSpacing(theme.SP_3)

        self.deadline_check = QCheckBox("Set deadline")
        self.deadline_check.setCursor(Qt.PointingHandCursor)

        self.deadline_date = QDateEdit(QDate.currentDate())
        self.deadline_date.setCalendarPopup(True)
        self.deadline_date.setDisplayFormat("yyyy-MM-dd")
        self.deadline_date.setMinimumWidth(190)
        self.deadline_date.setEnabled(False)

        self.deadline_time = QTimeEdit(QTime(14, 0))
        self.deadline_time.setDisplayFormat("HH:mm")
        self.deadline_time.setMinimumWidth(120)
        self.deadline_time.setEnabled(False)

        style_calendar_widget(self.deadline_date.calendarWidget())
        self.deadline_check.toggled.connect(self.deadline_date.setEnabled)
        self.deadline_check.toggled.connect(self.deadline_time.setEnabled)

        deadline_row.addWidget(self.deadline_check)
        deadline_row.addWidget(self.deadline_date)
        deadline_row.addWidget(self.deadline_time)
        deadline_row.addStretch(1)
        layout.addLayout(deadline_row)

        layout.addStretch(1)

        assign_button = QPushButton("📤   Assign Task")
        assign_button.setObjectName("PrimaryButton")
        assign_button.setMinimumHeight(54)
        assign_button.setCursor(Qt.PointingHandCursor)
        assign_button.clicked.connect(self._on_assign)
        layout.addWidget(assign_button)

        return card


    def _reload_assign_combo(self):
        """Fill the assignee combo with the real, approved employees.

        Assigning to a pending/rejected account would create a task its owner can
        never log in to see, so only approved accounts are offered; without a
        database the status list is used as-is.
        """
        if not hasattr(self, "assign_employee"):
            return

        current = self.assign_employee.currentData()

        if self.db is None:
            choices = [(e["full_name"], e["id"]) for e in self.employees]
        else:
            try:
                rows = self.db.get_all_employees()
            except Exception:
                logger.warning("assignee reload failed", exc_info=True)
                rows = []
            choices = [
                (row["full_name"], row["id"])
                for row in rows
                if row.get("status", "approved") == "approved"
            ]

        self.assign_employee.clear()
        for full_name, user_id in choices:
            self.assign_employee.addItem(full_name, user_id)

        if current is not None:
            index = self.assign_employee.findData(current)
            if index >= 0:
                self.assign_employee.setCurrentIndex(index)


    def _set_priority(self, priority):
        self.assign_priority = priority
        theme.repolish(self.normal_button)
        theme.repolish(self.urgent_button)


    def _on_assign(self):
        title = self.assign_title.text().strip()
        if not title:
            return
        description = self.assign_description.toPlainText().strip()
        deadline_date = deadline_time = None
        if self.deadline_check.isChecked():
            deadline_date = self.deadline_date.date().toString("yyyy-MM-dd")
            deadline_time = self.deadline_time.time().toString("HH:mm")

        employee_name = self.assign_employee.currentText() or "Unassigned"
        employee_id = self.assign_employee.currentData()
        priority = "Urgent" if self.assign_priority == "urgent" else "Normal"

        if self.db is not None:
            if employee_id is None:
                QMessageBox.warning(
                    self,
                    "No employee selected",
                    "There is no approved employee to assign this task to.",
                )
                return
            try:
                self.db.add_task(
                    employee_id,
                    title,
                    priority=self.assign_priority,
                    assigned_by=self.user.get("id"),
                    description=description or None,
                    deadline_date=deadline_date,
                    deadline_time=deadline_time,
                )
            except Exception as error:
                QMessageBox.critical(self, "Could not save task", str(error))
                return

        QMessageBox.information(
            self,
            "Task assigned",
            f"Assigned to: {employee_name}\nTask: {title}\nPriority: {priority}",
        )
        self.assign_title.clear()
        self.assign_description.clear()
        self.deadline_check.setChecked(False)
        self.refresh()




class ReportsPage(_Page):
    """Weekly report card (the table itself opens in a dialog)."""

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(user=user, db=db, parent=parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        content = QWidget()
        content.setObjectName("ScrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        body.setSpacing(theme.SP_5)
        body.addWidget(self._build_reports_card())
        body.addStretch(1)
        root.addWidget(self._page_scroll(content), 1)

    def _build_reports_card(self):
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_3)

        title = QLabel("📊   Weekly Reports")
        title.setObjectName("H3")
        layout.addWidget(title)

        description = QLabel(
            "Aggregated activity of the last 7 days for every employee: "
            "total focus time, away time, distraction time and the number "
            "of tracked sessions.\n\n"
            "Reports are generated locally from the session data stored on "
            "this device — nothing is uploaded."
        )
        description.setObjectName("MutedLabel")
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addStretch(1)

        reports_button = QPushButton("📈   View Weekly Reports")
        reports_button.setObjectName("PrimaryButton")
        reports_button.setMinimumHeight(54)
        reports_button.setCursor(Qt.PointingHandCursor)
        reports_button.clicked.connect(self._open_reports_dialog)
        layout.addWidget(reports_button)

        return card


    def _open_reports_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Weekly Reports")
        dialog.resize(900, 520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_4)

        title = QLabel("📊   Weekly Summary — Last 7 Days")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        table = QTableWidget(0, len(WEEKLY_HEADERS))
        table.setHorizontalHeaderLabels(WEEKLY_HEADERS)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        table.setShowGrid(False)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setFocusPolicy(Qt.NoFocus)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setHighlightSections(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        try:
            rows = self.db.get_weekly_report_all() if self.db else []
        except Exception as error:
            logger.warning("weekly report failed", exc_info=True)
            rows = []
            QMessageBox.warning(self, "Weekly Reports", f"Could not load data: {error}")

        for report in rows:
            row = table.rowCount()
            table.insertRow(row)
            table.setRowHeight(row, 52)

            name_item = QTableWidgetItem(f"🧑  {report['full_name']}")
            table.setItem(row, 0, name_item)

            values = [
                (_fmt_hms(report["total_focus"]), theme.TEXT_PRIMARY),
                (_fmt_hms(report["total_distraction"]), theme.WARNING),
                (_fmt_hms(report["total_away"]), theme.TEXT_MUTED),
                (str(report["total_sessions"]), theme.TEXT_PRIMARY),
            ]
            for offset, (value, color) in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setForeground(QColor(color))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, offset, item)

        if not rows:
            table.setRowCount(1)
            item = QTableWidgetItem("No employees yet.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            table.setItem(0, 0, item)
            table.setSpan(0, 0, 1, len(WEEKLY_HEADERS))

        layout.addWidget(table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec_()




class ManagerScreen(ShellNavigationMixin, QWidget):
    """Manager workspace shell: sidebar on the left, page stack on the right."""

    logout_requested = pyqtSignal()

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": 1, "full_name": "Admin Manager"}
        self.db = db
        self.full_name = self.user.get("full_name", "Manager")

        self.sidebar = Sidebar(user=self.user, items=MANAGER_ITEMS)
        self.sidebar.navigate.connect(self._navigate)
        self.sidebar.logout_requested.connect(self.logout_requested)

        from ui.ai_chat_screen import AIChatScreen
        from ui.ai_helper_screen import AIHelperScreen
        from ui.knowledge_screen import KnowledgeScreen
        from ui.manager_home_screen import ManagerHomeScreen
        from ui.settings_screen import SettingsScreen
        from ui.todo_screen import TodoScreen

        self.home_page = ManagerHomeScreen(user=self.user, db=self.db)
        self.employees_page = EmployeeStatusPage(user=self.user, db=self.db)
        self.sessions_page = SessionsHistoryPage(user=self.user, db=self.db)
        self.tasks_page = TasksPage(user=self.user, db=self.db)
        self.reports_page = ReportsPage(user=self.user, db=self.db)
        self.ai_helper_page = AIHelperScreen(user=self.user, db=self.db)
        self.ai_chat_page = AIChatScreen(user=self.user, db=self.db)
        self.knowledge_page = KnowledgeScreen(user=self.user, db=self.db)
        self.todo_page = TodoScreen(user=self.user, db=self.db)
        self.settings_page = SettingsScreen(user=self.user, db=self.db)
        self.settings_page.profile_updated.connect(self._on_profile_updated)
        self.calendar_page = CalendarScreen(user=self.user, db=self.db)

        self.employees_page.employees_changed.connect(self.tasks_page.refresh)
        self.home_page.go_to_employees.connect(
            lambda: self._navigate("employees")
        )

        self.stack = QStackedWidget()
        self._page_index = {}
        for key, page in (
            ("home", self.home_page),
            ("calendar", self.calendar_page),
            ("employees", self.employees_page),
            ("sessions", self.sessions_page),
            ("tasks", self.tasks_page),
            ("reports", self.reports_page),
            ("ai_helper", self.ai_helper_page),
            ("ai_chat", self.ai_chat_page),
            ("knowledge", self.knowledge_page),
            ("todo", self.todo_page),
            ("settings", self.settings_page),
        ):
            self._page_index[key] = self.stack.addWidget(page)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar)
        root.addWidget(self.stack, 1)

        # Kept for callers that read the previous single-screen attributes.
        self.employees = []

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(30000)
        self.refresh_timer.timeout.connect(self._refresh_visible)
        self.refresh_timer.start()

        # Calendar badge: today's event count, refreshed every 30 s.
        self.badge_timer = QTimer(self)
        self.badge_timer.setInterval(30000)
        self.badge_timer.timeout.connect(self._refresh_calendar_badge)
        self.badge_timer.start()
        self.calendar_page.changed.connect(self._refresh_calendar_badge)
        self._refresh_calendar_badge()

        self._navigate("home")

    # ------------------------------------------------------------------ #
    #  Navigation
    # ------------------------------------------------------------------ #
    def _on_profile_updated(self, full_name, _username):
        """The Settings page saved a new name: show it in the sidebar/greeting."""
        self.full_name = full_name
        self.sidebar.set_user(full_name)
        self.home_page.full_name = full_name
        self.home_page.refresh()

    def _refresh_visible(self):
        """Auto-refresh whatever page the manager is looking at."""
        page = self.stack.currentWidget()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()
        if hasattr(page, "employees"):
            self.employees = page.employees

    # ------------------------------------------------------------------ #
    #  Compatibility helpers (previous single-screen API)
    # ------------------------------------------------------------------ #
    def _reload_all(self):
        for page in (self.employees_page, self.sessions_page, self.tasks_page):
            page.refresh()

    def _reload_history(self):
        self.sessions_page._reload_history()

    def _reload_pending(self):
        self.employees_page._reload_pending()

    def _reload_assign_combo(self):
        self.tasks_page._reload_assign_combo()

    def _initials(self):
        parts = [part for part in str(self.full_name).split() if part]
        if not parts:
            return "?"
        return "".join(part[0].upper() for part in parts[:2]) or "?"

    def _open_session_detail(self, session_id):
        self.sessions_page._open_session_detail(session_id)

    def _open_reports_dialog(self):
        self.reports_page._open_reports_dialog()

    @property
    def table(self):
        """Alias of ``employees_page.table`` (kept from the single-screen API)."""
        return self.employees_page.table

    @property
    def pending_table(self):
        """Alias of ``employees_page.pending_table`` (kept from the single-screen API)."""
        return self.employees_page.pending_table

    @property
    def history_table(self):
        """Alias of ``sessions_page.history_table`` (kept from the single-screen API)."""
        return self.sessions_page.history_table

    @property
    def history_user(self):
        """Alias of ``sessions_page.history_user`` (kept from the single-screen API)."""
        return self.sessions_page.history_user

    @property
    def history_range(self):
        """Alias of ``sessions_page.history_range`` (kept from the single-screen API)."""
        return self.sessions_page.history_range

    @property
    def assign_employee(self):
        """Alias of ``tasks_page.assign_employee`` (kept from the single-screen API)."""
        return self.tasks_page.assign_employee

    @property
    def assign_title(self):
        """Alias of ``tasks_page.assign_title`` (kept from the single-screen API)."""
        return self.tasks_page.assign_title

    @property
    def urgent_button(self):
        """Alias of ``tasks_page.urgent_button`` (kept from the single-screen API)."""
        return self.tasks_page.urgent_button

    @property
    def normal_button(self):
        """Alias of ``tasks_page.normal_button`` (kept from the single-screen API)."""
        return self.tasks_page.normal_button
