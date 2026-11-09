"""Meetings page: meeting requests between an employee and the manager (online only).

* An **employee** asks for a meeting (topic, short note, 1-3 proposed times) and sees
  their requests. When the manager proposes other times, the employee picks one or
  cancels.
* A **manager** sees the team's requests: accept one proposed time (it goes into both
  calendars), decline with a reason, or propose other times. An accepted meeting can be
  cancelled by either side.

The server decides what is allowed (see backend ``routers/meeting_requests.py``); this
page only offers the buttons that make sense for the request's state. Dialogs are opened
through small methods (``_ask_reason``, ``_ask_times``, ``_confirm``) so tests can answer them.
"""
import logging
from datetime import datetime, timedelta

from PyQt5.QtCore import QDateTime, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QVBoxLayout, QWidget,
)

from ui import theme
from ui.widgets import clear_layout, make_card

logger = logging.getLogger(__name__)

MAX_TIMES = 3
DURATIONS = (15, 30, 45, 60, 90)
STATUS_TEXT = {"pending": "Waiting for the manager", "rescheduled": "New times proposed", "accepted": "Booked",
               "declined": "Declined", "cancelled": "Cancelled"}
STATUS_PILL = {"pending": "PillDistracted", "rescheduled": "PillAccent", "accepted": "PillPresent",
               "declined": "PillUrgent", "cancelled": "PillMuted"}
ONLINE_ONLY = "Meeting requests need the online server. Sign in with your company account to use them."
DISPLAY_FORMAT = "ddd d MMM yyyy  HH:mm"


def show_time(iso: str) -> str:
    """An ISO time from the server, shown in this computer's local time."""
    moment = datetime.fromisoformat(iso).astimezone()
    return f"{moment:%a} {moment.day} {moment:%b %Y}, {moment:%H:%M}"


def next_slot(days=1, hour=10) -> QDateTime:
    """A sensible default for a new proposed time: tomorrow (or later) at 10:00."""
    day = datetime.now() + timedelta(days=days)
    return QDateTime(day.replace(hour=hour, minute=0, second=0, microsecond=0))


def to_aware(edit: QDateTimeEdit) -> datetime:
    return edit.dateTime().toPyDateTime().astimezone()


def _time_edit(value: QDateTime) -> QDateTimeEdit:
    edit = QDateTimeEdit(value)
    edit.setCalendarPopup(True)
    edit.setDisplayFormat(DISPLAY_FORMAT)
    edit.setMinimumDateTime(QDateTime.currentDateTime())
    edit.setMinimumWidth(220)
    return edit


class TimesEditor(QWidget):
    """1-3 date-time pickers with "add another" and remove buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.edits = []
        self._rows = QVBoxLayout()
        self._rows.setSpacing(theme.SP_2)
        self.add_button = QPushButton("+  Add another time")
        self.add_button.setObjectName("GhostButton")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(lambda: self.add_time())
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addLayout(self._rows)
        column.addWidget(self.add_button, 0, Qt.AlignLeft)
        self.reset()

    def reset(self):
        clear_layout(self._rows)
        self.edits = []
        self.add_time(next_slot(1))

    def add_time(self, value=None):
        if len(self.edits) >= MAX_TIMES:
            return
        edit = _time_edit(value or next_slot(len(self.edits) + 1))
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(edit)
        remove = QPushButton("Remove")
        remove.setObjectName("GhostButton")
        remove.setCursor(Qt.PointingHandCursor)
        remove.clicked.connect(lambda: self._remove(row, edit))
        line.addWidget(remove)
        line.addStretch(1)
        self._rows.addWidget(row)
        self.edits.append(edit)
        self._sync()

    def _remove(self, row, edit):
        if len(self.edits) <= 1:
            return
        self.edits.remove(edit)
        row.setParent(None)
        row.deleteLater()
        self._sync()

    def _sync(self):
        self.add_button.setEnabled(len(self.edits) < MAX_TIMES)
        for index in range(self._rows.count()):
            remove = self._rows.itemAt(index).widget().findChildren(QPushButton)
            for button in remove:
                button.setVisible(len(self.edits) > 1)

    def times(self) -> list:
        return [to_aware(edit) for edit in self.edits]


class TimesDialog(QDialog):
    """The manager proposes other times (with an optional note)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Propose other times")
        self.editor = TimesEditor()
        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional note, e.g. “I'm travelling that week”")
        self.note.setMaxLength(1000)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Send")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column = QVBoxLayout(self)
        column.addWidget(QLabel("Up to three times the employee can choose from:"))
        column.addWidget(self.editor)
        column.addWidget(self.note)
        column.addWidget(buttons)


class RequestCard(QFrame):
    """One request: what was asked, its state, and the actions allowed now."""

    def __init__(self, row: dict, manager_view: bool, parent=None):
        super().__init__(parent)
        self.row = row
        self.setObjectName("TaskRow")
        column = QVBoxLayout(self)
        column.setContentsMargins(theme.SP_4, theme.SP_3, theme.SP_4, theme.SP_3)
        column.setSpacing(theme.SP_2)

        top = QHBoxLayout()
        title = QLabel(row["topic"])
        title.setObjectName("TaskTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        self.pill = QLabel(STATUS_TEXT.get(row["status"], row["status"]))
        self.pill.setObjectName(STATUS_PILL.get(row["status"], "PillMuted"))
        top.addWidget(self.pill, 0, Qt.AlignTop)
        column.addLayout(top)

        asked = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).astimezone()
        who = (f"From {row['requested_by_name']}" if manager_view
               else f"To {row['manager_name']}" if row.get("manager_name") else "To your manager")
        meta = QLabel(f"{who} · asked {asked:%a} {asked.day} {asked:%b} · {row['duration_minutes']} min")
        meta.setObjectName("MutedLabel")
        column.addWidget(meta)
        if row.get("note"):
            column.addWidget(self._text(f"“{row['note']}”"))

        self.time_group = QButtonGroup(self)
        self.time_buttons = []
        choosing = row["waiting_for"] == ("manager" if manager_view else "employee")
        if row["status"] == "accepted" and row.get("chosen_time"):
            column.addWidget(self._text(f"<b>Booked:</b> {show_time(row['chosen_time'])} — in both calendars", rich=True))
        elif row["status"] in ("pending", "rescheduled"):
            label = "Proposed times" if row["status"] == "pending" else "Times proposed by the manager"
            column.addWidget(self._muted(label + (" — pick one:" if choosing else ":")))
            for index, iso in enumerate(row["proposed_times"]):
                if choosing:
                    button = QRadioButton(show_time(iso))
                    button.setProperty("iso", iso)
                    button.setChecked(index == 0)
                    self.time_group.addButton(button)
                    self.time_buttons.append(button)
                    column.addWidget(button)
                else:
                    column.addWidget(self._text("•  " + show_time(iso)))
        if row.get("reply_note"):
            column.addWidget(self._text(f"<b>Manager's note:</b> {_escape(row['reply_note'])}", rich=True))
        if row.get("decline_reason"):
            label = "Reason" if row["status"] == "declined" else "Note"
            column.addWidget(self._text(f"<b>{label}:</b> {_escape(row['decline_reason'])}", rich=True))

        self.actions = QHBoxLayout()
        self.actions.setSpacing(theme.SP_2)
        self.buttons = {}
        column.addLayout(self.actions)

    def add_action(self, key, text, style="GhostButton"):
        button = QPushButton(text)
        button.setObjectName(style)
        button.setCursor(Qt.PointingHandCursor)
        self.actions.addWidget(button)
        self.buttons[key] = button
        return button

    def chosen_time(self):
        button = self.time_group.checkedButton()
        return button.property("iso") if button is not None else None

    @staticmethod
    def _text(text, rich=False):
        label = QLabel(text)
        label.setObjectName("BodyLabel")
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText if rich else Qt.PlainText)
        return label

    @staticmethod
    def _muted(text):
        label = QLabel(text)
        label.setObjectName("MutedLabel")
        return label


def _escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class MeetingsScreen(QWidget):
    """The Meetings page for both roles."""

    #: a request changed (the shell refreshes the sidebar badge)
    changed = pyqtSignal()

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": None, "full_name": "", "role": "employee"}
        self.db = db
        self.is_manager = self.user.get("role") == "manager"
        self.cards = []
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("ScrollContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        body.setSpacing(theme.SP_4)
        scroll.setWidget(content)
        root.addWidget(scroll)

        heading = QLabel("Meetings")
        heading.setObjectName("H1")
        body.addWidget(heading)
        lead = QLabel("Requests from your team: accept a time, propose another one, or decline."
                      if self.is_manager else
                      "Ask your manager for a meeting and follow the answer here. Accepted meetings appear in "
                      "your calendar.")
        lead.setObjectName("LeadLabel")
        lead.setWordWrap(True)
        body.addWidget(lead)

        self.notice = QLabel("")
        self.notice.setObjectName("ErrorLabel")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        body.addWidget(self.notice)

        if not self.is_manager:
            body.addWidget(self._build_request_card())

        card, layout = make_card("Requests from your team" if self.is_manager else "Your requests")
        bar = QHBoxLayout()
        bar.addWidget(self._caption("Show"))
        self.filter_combo = QComboBox()
        for label, value in (("Open", "open"), ("Booked", "accepted"), ("All", None)):
            self.filter_combo.addItem(label, value)
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.filter_combo)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(theme.SP_3)
        layout.addLayout(self.list_layout)
        self.empty_label = QLabel("")
        self.empty_label.setObjectName("EmptyLabel")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        body.addWidget(card)
        body.addStretch(1)

    def _build_request_card(self):
        card, layout = make_card("Request a meeting", "Propose up to three times; your manager picks one or "
                                                      "suggests another.")
        layout.addWidget(self._caption("Topic"))
        self.topic_input = QLineEdit()
        self.topic_input.setPlaceholderText("e.g. Salary review, project plan, time off")
        self.topic_input.setMaxLength(200)
        layout.addWidget(self.topic_input)
        layout.addWidget(self._caption("Short note (optional)"))
        self.note_input = QPlainTextEdit()
        self.note_input.setPlaceholderText("What would you like to talk about?")
        self.note_input.setFixedHeight(70)
        layout.addWidget(self.note_input)
        layout.addWidget(self._caption("Proposed times"))
        self.times_editor = TimesEditor()
        layout.addWidget(self.times_editor)
        row = QHBoxLayout()
        row.addWidget(self._caption("Length"))
        self.duration_combo = QComboBox()
        for minutes in DURATIONS:
            self.duration_combo.addItem(f"{minutes} min", minutes)
        self.duration_combo.setCurrentIndex(DURATIONS.index(30))
        row.addWidget(self.duration_combo)
        row.addStretch(1)
        self.send_button = QPushButton("Send request")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(self._on_send)
        row.addWidget(self.send_button)
        layout.addLayout(row)
        self.form_status = QLabel("")
        self.form_status.setWordWrap(True)
        self.form_status.setVisible(False)
        layout.addWidget(self.form_status)
        return card

    @staticmethod
    def _caption(text):
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def _online(self):
        return self.db is not None and getattr(self.db, "api", None) is not None

    def refresh(self):
        clear_layout(self.list_layout)
        self.cards = []
        if not self._online():
            self._notice(ONLINE_ONLY)
            self.empty_label.setVisible(False)
            if not self.is_manager:
                self.send_button.setEnabled(False)
            return
        if self.notice.text() == ONLINE_ONLY:
            self._notice("")                     # a periodic reload keeps the last action's message
        rows = self.db.get_meeting_requests(self.filter_combo.currentData())
        for row in rows:
            card = RequestCard(row, self.is_manager)
            self._wire(card)
            self.cards.append(card)
            self.list_layout.addWidget(card)
        empty = {"open": "Nothing waiting." if self.is_manager else "No open requests.",
                 "accepted": "No booked meetings.", None: "No requests yet."}[self.filter_combo.currentData()]
        self.empty_label.setText(empty)
        self.empty_label.setVisible(not rows)

    def _notice(self, text):
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def _wire(self, card: RequestCard):
        row, status = card.row, card.row["status"]
        if self.is_manager:
            if status == "pending":
                card.add_action("accept", "Accept selected time", "PrimaryButton").clicked.connect(
                    lambda: self._accept(card))
            if status in ("pending", "rescheduled"):
                card.add_action("reschedule", "Propose other times").clicked.connect(lambda: self._reschedule(card))
                card.add_action("decline", "Decline…", "DangerButton").clicked.connect(lambda: self._decline(card))
            if status == "accepted":
                card.add_action("cancel", "Cancel meeting", "DangerButton").clicked.connect(lambda: self._cancel(card))
        else:
            if status == "rescheduled":
                card.add_action("accept", "Accept selected time", "PrimaryButton").clicked.connect(
                    lambda: self._accept(card))
            if status in ("pending", "rescheduled", "accepted"):
                text = "Cancel meeting" if status == "accepted" else "Cancel request"
                card.add_action("cancel", text, "DangerButton").clicked.connect(lambda: self._cancel(card))
        card.actions.addStretch(1)
        if row["status"] == "rescheduled" and self.is_manager:
            card.actions.insertWidget(0, RequestCard._muted("Waiting for the employee to pick a time."))
        if row["status"] == "pending" and not self.is_manager:
            card.actions.insertWidget(0, RequestCard._muted("Waiting for the manager."))

    # ------------------------------------------------------------------ #
    #  Dialogs (replaced in tests)
    # ------------------------------------------------------------------ #
    def _ask_reason(self, title, prompt, required=True):
        text, ok = QInputDialog.getMultiLineText(self, title, prompt)
        text = text.strip()
        if not ok or (required and not text):
            return None
        return text

    def _ask_times(self):
        dialog = TimesDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return dialog.editor.times(), dialog.note.text().strip()

    def _confirm(self, title, text):
        return QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _done(self, ok, result, success_text):
        if not ok:
            self._notice(str(result))
            return False
        self.refresh()
        self.changed.emit()
        self._flash(success_text)
        return True

    def _flash(self, text):
        self.notice.setObjectName("SuccessLabel")
        theme.repolish(self.notice)
        self.notice.setText(text)
        self.notice.setVisible(True)
        self.notice.setObjectName("ErrorLabel")

    def _on_send(self):
        topic = self.topic_input.text().strip()
        if not topic:
            self._form_status("Please enter a topic.", False)
            return
        times = self.times_editor.times()
        ok, result = self.db.request_meeting(topic, times, note=self.note_input.toPlainText().strip() or None,
                                             duration_minutes=self.duration_combo.currentData())
        if not ok:
            self._form_status(str(result), False)
            return
        self._form_status("Request sent. Your manager has been notified.", True)
        self.topic_input.clear()
        self.note_input.clear()
        self.times_editor.reset()
        self.filter_combo.setCurrentIndex(0)
        self.refresh()
        self.changed.emit()

    def _form_status(self, text, ok):
        self.form_status.setObjectName("SuccessLabel" if ok else "ErrorLabel")
        theme.repolish(self.form_status)
        self.form_status.setText(text)
        self.form_status.setVisible(True)

    def _accept(self, card):
        time = card.chosen_time()
        if time is None:
            self._notice("Pick one of the proposed times first.")
            return
        ok, result = self.db.accept_meeting_request(card.row["id"], time)
        self._done(ok, result, f"Booked for {show_time(time)}. It is in both calendars.")

    def _decline(self, card):
        reason = self._ask_reason("Decline the request", "Tell the employee why (required):")
        if reason is None:
            return
        ok, result = self.db.decline_meeting_request(card.row["id"], reason)
        self._done(ok, result, "Declined. The employee has been told.")

    def _reschedule(self, card):
        answer = self._ask_times()
        if answer is None:
            return
        times, note = answer
        ok, result = self.db.reschedule_meeting_request(card.row["id"], times, note or None)
        self._done(ok, result, "Other times sent. The employee will pick one.")

    def _cancel(self, card):
        booked = card.row["status"] == "accepted"
        if not self._confirm("Cancel meeting" if booked else "Cancel request",
                             "Cancel this meeting? It will be removed from both calendars." if booked
                             else "Cancel this meeting request?"):
            return
        ok, result = self.db.cancel_meeting_request(card.row["id"])
        self._done(ok, result, "Cancelled. The other side has been told.")
