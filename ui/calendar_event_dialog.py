"""Dialogs for calendar events: create / edit (manager) and read-only details.

:class:`CalendarEventDialog` is used for both creating and editing; in edit mode
it also offers a Delete button (with a confirmation).  :class:`CalendarEventDetailDialog`
is the read-only view every other user gets when they click an event.
"""

import logging
from datetime import datetime

from PyQt5.QtCore import QDate, QTime, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.calendar_screen import style_calendar_widget

logger = logging.getLogger(__name__)

DEFAULT_START = QTime(9, 0)
DEFAULT_END = QTime(10, 0)


def describe_event_time(event):
    """``"09:30 – 10:00"``, ``"09:30"`` or ``"All day"`` for an event row."""
    start, end = event.get("start_time"), event.get("end_time")
    if start and end:
        return "%s – %s" % (start, end)
    return start or "All day"


class CalendarEventDialog(QDialog):
    """Create (``event_id=None``) or edit one calendar event."""

    #: Emitted after the event was created, changed or deleted.
    saved = pyqtSignal()

    def __init__(self, db, manager_id, event_id=None, parent=None, default_date=None):
        super().__init__(parent)
        self.db = db
        self.manager_id = manager_id
        self.event_id = event_id
        self.created_id = None
        self.setWindowTitle("Edit Event" if event_id else "Create Event")
        self.setMinimumWidth(640)

        self._employees = self._load_employees()
        self._boxes = {}            # employee id -> QCheckBox
        self._build_ui(default_date)
        if event_id is not None:
            self._load_event()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _load_employees(self):
        """Approved employees: the only people that can be invited."""
        try:
            return [row for row in self.db.get_all_employees()
                    if row.get("status", "approved") == "approved"]
        except Exception:
            logger.warning("could not list employees", exc_info=True)
            return []

    @staticmethod
    def _caption(text):
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _build_ui(self, default_date):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SP_6, theme.SP_5, theme.SP_6, theme.SP_5)
        layout.setSpacing(theme.SP_2)

        heading = QLabel("Edit Event" if self.event_id else "Create Event")
        heading.setObjectName("H3")
        layout.addWidget(heading)

        layout.addWidget(self._caption("Title"))
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Event title...")
        self.title_input.setMinimumHeight(theme.FIELD_HEIGHT)
        layout.addWidget(self.title_input)

        self._add_date_row(layout, default_date)
        self._add_time_row(layout)
        self._add_description(layout)
        self._add_attendees(layout)
        self._add_footer(layout)

    def _add_date_row(self, layout, default_date):
        """The date picker."""
        layout.addWidget(self._caption("Date"))
        row = QHBoxLayout()
        self.date_edit = QDateEdit(default_date or QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setMinimumWidth(190)
        style_calendar_widget(self.date_edit.calendarWidget())
        row.addWidget(self.date_edit)
        row.addStretch(1)
        layout.addLayout(row)

    def _add_time_row(self, layout):
        """The optional start and end time."""
        times = QHBoxLayout()
        times.setSpacing(theme.SP_3)
        self.start_check = QCheckBox("Set start time")
        self.start_edit = QTimeEdit(DEFAULT_START)
        self.end_check = QCheckBox("Set end time")
        self.end_edit = QTimeEdit(DEFAULT_END)
        for check, edit in ((self.start_check, self.start_edit),
                            (self.end_check, self.end_edit)):
            edit.setDisplayFormat("HH:mm")
            edit.setMinimumWidth(110)
            edit.setEnabled(False)
            check.setCursor(Qt.PointingHandCursor)
            check.toggled.connect(edit.setEnabled)
        times.addWidget(self.start_check)
        times.addWidget(self.start_edit)
        times.addSpacing(theme.SP_4)
        times.addWidget(self.end_check)
        times.addWidget(self.end_edit)
        times.addStretch(1)
        layout.addLayout(times)

    def _add_description(self, layout):
        """The free-text description."""
        layout.addWidget(self._caption("Description"))
        self.description_edit = QPlainTextEdit()
        self.description_edit.setObjectName("TaskDescriptionInput")
        self.description_edit.setPlaceholderText("Description (optional)…")
        # the global input rule has min-height: 24px, which would beat setMinimumHeight
        self.description_edit.setStyleSheet("min-height: 90px;")
        layout.addWidget(self.description_edit)

    def _add_attendees(self, layout):
        """"All employees" plus one check box per approved employee."""
        layout.addWidget(self._caption("Attendees"))
        self.all_check = QCheckBox("All employees")
        self.all_check.setCursor(Qt.PointingHandCursor)
        self.all_check.toggled.connect(self._on_all_toggled)
        layout.addWidget(self.all_check)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumHeight(130)
        scroll.setMaximumHeight(190)
        holder = QWidget()
        holder.setObjectName("ScrollContent")
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(theme.SP_2, theme.SP_1, theme.SP_2, theme.SP_1)
        holder_layout.setSpacing(theme.SP_2)
        if not self._employees:
            empty = QLabel("No approved employees yet.")
            empty.setObjectName("MutedLabel")
            holder_layout.addWidget(empty)
        for employee in self._employees:
            box = QCheckBox(employee["full_name"])
            box.setCursor(Qt.PointingHandCursor)
            self._boxes[employee["id"]] = box
            holder_layout.addWidget(box)
        holder_layout.addStretch(1)
        scroll.setWidget(holder)
        layout.addWidget(scroll)

    def _add_footer(self, layout):
        """The error line and the Delete / Cancel / Save buttons."""
        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP_3)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.clicked.connect(self._on_delete)
        self.delete_button.setVisible(self.event_id is not None)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("GhostButton")
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)

        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.clicked.connect(self._on_save)
        buttons.addWidget(self.save_button)
        layout.addSpacing(theme.SP_2)
        layout.addLayout(buttons)


    def _on_all_toggled(self, checked):
        """"All employees" ticks every box and locks the list."""
        for box in self._boxes.values():
            if checked:
                box.setChecked(True)
            box.setEnabled(not checked)

    def _show_error(self, message):
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    # ------------------------------------------------------------------ #
    #  Edit mode: fill the form
    # ------------------------------------------------------------------ #
    def _load_event(self):
        """Prefill every field from the stored event."""
        event = self.db.get_calendar_event(self.event_id)
        if event is None:
            self._show_error("This event no longer exists.")
            self.save_button.setEnabled(False)
            return
        self.title_input.setText(event["title"])
        self.date_edit.setDate(QDate.fromString(event["event_date"], "yyyy-MM-dd"))
        if event["start_time"]:
            self.start_edit.setTime(QTime.fromString(event["start_time"], "HH:mm"))
            self.start_check.setChecked(True)
        if event["end_time"]:
            self.end_edit.setTime(QTime.fromString(event["end_time"], "HH:mm"))
            self.end_check.setChecked(True)
        self.description_edit.setPlainText(event["description"] or "")

        invited = {attendee["id"] for attendee in event["attendees"]}
        for employee_id, box in self._boxes.items():
            box.setChecked(employee_id in invited)
        if self._boxes and invited >= set(self._boxes):
            self.all_check.setChecked(True)

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def selected_attendee_ids(self):
        """Employee ids that will be invited (everybody when "All" is ticked)."""
        if self.all_check.isChecked():
            return list(self._boxes)
        return [employee_id for employee_id, box in self._boxes.items()
                if box.isChecked()]

    def _on_save(self):
        title = self.title_input.text().strip()
        if not title:
            self._show_error("Please enter a title.")
            return
        if not self.date_edit.date().isValid():
            self._show_error("Please choose a date.")
            return

        event_date = self.date_edit.date().toString("yyyy-MM-dd")
        start = self.start_edit.time().toString("HH:mm") if self.start_check.isChecked() else None
        end = self.end_edit.time().toString("HH:mm") if self.end_check.isChecked() else None
        if end and not start:
            self._show_error("An end time needs a start time.")
            return
        if start and end and end <= start:
            self._show_error("The end time must be after the start time.")
            return
        description = self.description_edit.toPlainText().strip() or None

        try:
            if self.event_id is None:
                self.created_id = self.db.create_calendar_event(
                    title, event_date, self.manager_id, description=description,
                    start_time=start, end_time=end,
                )
                event_id = self.created_id
            else:
                ok, message = self.db.update_calendar_event(
                    self.event_id, title=title, event_date=event_date,
                    description=description, start_time=start, end_time=end,
                )
                if not ok:
                    self._show_error(message)
                    return
                event_id = self.event_id
            ok, message = self.db.set_calendar_attendees(
                event_id, self.selected_attendee_ids()
            )
            if not ok:
                self._show_error(message)
                return
        except Exception:
            logger.warning("save failed", exc_info=True)
            self._show_error("Could not save the event. Please try again.")
            return

        self.saved.emit()
        self.accept()

    def _on_delete(self):
        answer = QMessageBox.question(
            self, "Delete event",
            f"Delete “{self.title_input.text().strip()}” for everyone invited?",
            QMessageBox.Cancel | QMessageBox.Yes, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            ok, message = self.db.delete_calendar_event(self.event_id)
        except Exception:
            logger.warning("delete failed", exc_info=True)
            ok, message = False, "Could not delete the event."
        if not ok:
            self._show_error(message)
            return
        self.saved.emit()
        self.accept()


class CalendarEventDetailDialog(QDialog):
    """Read-only view of an event (for everybody who did not create it)."""

    def __init__(self, db, event_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Event details")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SP_6, theme.SP_5, theme.SP_6, theme.SP_5)
        layout.setSpacing(theme.SP_2)

        event = db.get_calendar_event(event_id)
        if event is None:
            missing = QLabel("This event no longer exists.")
            missing.setObjectName("ErrorLabel")
            layout.addWidget(missing)
        else:
            title = QLabel(event["title"])
            title.setObjectName("H3")
            title.setWordWrap(True)
            layout.addWidget(title)

            try:
                day = datetime.strptime(event["event_date"], "%Y-%m-%d")
                when = "%s  ·  %s" % (day.strftime("%A, %B %d, %Y"),
                                          describe_event_time(event))
            except ValueError:
                when = event["event_date"]
            layout.addWidget(self._line(when, "LeadLabel"))
            layout.addWidget(self._line("Organised by %s" % event["created_by_name"],
                                        "MutedLabel"))

            if event["description"]:
                layout.addSpacing(theme.SP_2)
                layout.addWidget(self._line(event["description"], "BodyLabel"))

            layout.addSpacing(theme.SP_2)
            names = ", ".join(a["full_name"] for a in event["attendees"]) or "—"
            layout.addWidget(self._line("Attendees (%d)" % event["attendee_count"], "FieldLabel"))
            layout.addWidget(self._line(names, "BodyLabel"))

        layout.addSpacing(theme.SP_3)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("PrimaryButton")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    @staticmethod
    def _line(text, object_name):
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        return label
