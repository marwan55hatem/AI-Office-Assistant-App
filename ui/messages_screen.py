"""Messages page: the private chat between each employee and the managers (online only).

* An **employee** sees one conversation, with the company's managers.
* A **manager** sees a list of conversations (one per employee, unread counts, the
  newest first) and the selected chat beside it.

Messages go out over HTTP; the live channel (:class:`cloud.chat_socket.ChatSocket`)
brings the other side's messages, read receipts and typing hints at once. While it is
down the page polls every few seconds, so nothing is missed either way.

Own messages show "Sent", "Delivered" (it reached the other side's device) or "Read".
"""
import logging
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ui import theme
from ui.widgets import clear_layout

logger = logging.getLogger(__name__)

MAX_CHARS = 4000
POLL_MS = 5000
TYPING_SEND_MS = 3000
TYPING_SHOW_MS = 4000
ONLINE_ONLY = "Messages need the online server. Sign in with your company account to use them."


def clock(iso: str) -> str:
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    today = datetime.now().astimezone().date()
    return f"{moment:%H:%M}" if moment.date() == today else f"{moment:%a} {moment.day} {moment:%b}, {moment:%H:%M}"


def state_text(message: dict) -> str:
    if message.get("read_at"):
        return "Read"
    if message.get("delivered_at"):
        return "Delivered"
    return "Sent"


class Composer(QPlainTextEdit):
    """The message box: Enter sends, Shift+Enter starts a new line."""

    submitted = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class Bubble(QFrame):
    """One message: text, time and (for your own) its state."""

    def __init__(self, message: dict, mine: bool, sender_name: str, parent=None):
        super().__init__(parent)
        self.message = message
        self.mine = mine
        self.setObjectName("ChatBubbleMine" if mine else "ChatBubbleTheirs")
        column = QVBoxLayout(self)
        column.setContentsMargins(theme.SP_3, theme.SP_2, theme.SP_3, theme.SP_2)
        column.setSpacing(2)
        if not mine and sender_name:
            name = QLabel(sender_name)
            name.setObjectName("ChatSender")
            column.addWidget(name)
        self.text = QLabel(message["body"])
        self.text.setTextFormat(Qt.PlainText)                  # user text is never markup
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text.setObjectName("ChatText")
        column.addWidget(self.text)
        self.meta = QLabel("")
        self.meta.setObjectName("ChatMeta")
        self.meta.setAlignment(Qt.AlignRight)
        column.addWidget(self.meta)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.setMaximumWidth(560)
        self.refresh_meta()

    def update_message(self, **changes):
        self.message.update(changes)
        self.refresh_meta()

    def refresh_meta(self):
        when = clock(self.message["created_at"])
        self.meta.setText(f"{when} · {state_text(self.message)}" if self.mine else when)


class ChatView(QWidget):
    """One conversation: history (with "load earlier"), the typing hint and the composer."""

    sent = pyqtSignal()

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.employee_id = None
        self.bubbles = {}                     # message id -> Bubble
        self.has_more = False
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SP_2)

        self.title = QLabel("")
        self.title.setObjectName("H3")
        column.addWidget(self.title)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("MutedLabel")
        column.addWidget(self.subtitle)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("ScrollContent")
        self.list = QVBoxLayout(holder)
        self.list.setSpacing(theme.SP_2)
        self.list.setContentsMargins(theme.SP_2, theme.SP_2, theme.SP_2, theme.SP_2)
        self.earlier_button = QPushButton("Load earlier messages")
        self.earlier_button.setObjectName("GhostButton")
        self.earlier_button.setCursor(Qt.PointingHandCursor)
        self.earlier_button.clicked.connect(self.load_earlier)
        self.list.addWidget(self.earlier_button, 0, Qt.AlignHCenter)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(theme.SP_2)
        self.list.addLayout(self.rows)
        self.empty = QLabel("No messages yet. Say hello!")
        self.empty.setObjectName("EmptyLabel")
        self.empty.setAlignment(Qt.AlignCenter)
        self.list.addWidget(self.empty)
        self.list.addStretch(1)
        self.scroll.setWidget(holder)
        column.addWidget(self.scroll, 1)

        self.typing_label = QLabel("")
        self.typing_label.setObjectName("MutedLabel")
        column.addWidget(self.typing_label)
        self._typing_clear = QTimer(self)
        self._typing_clear.setSingleShot(True)
        self._typing_clear.timeout.connect(lambda: self.typing_label.setText(""))

        composer = QHBoxLayout()
        self.input = Composer()
        self.input.setPlaceholderText("Write a message…  (Enter to send, Shift+Enter for a new line)")
        self.input.setFixedHeight(64)
        self.input.submitted.connect(self.send)
        self.input.textChanged.connect(self._on_text_changed)
        composer.addWidget(self.input, 1)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(self.send)
        composer.addWidget(self.send_button, 0, Qt.AlignBottom)
        column.addLayout(composer)
        self.status = QLabel("")
        self.status.setObjectName("ErrorLabel")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        column.addWidget(self.status)
        self._last_typing_sent = 0.0
        self.set_enabled(False)

    # ------------------------------------------------------------------ state
    def set_enabled(self, enabled):
        for widget in (self.input, self.send_button):
            widget.setEnabled(enabled)

    def open(self, employee_id, title, subtitle="", can_write=True):
        self.employee_id = employee_id
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.typing_label.setText("")
        self.status.setVisible(False)
        clear_layout(self.rows)
        self.bubbles = {}
        page = self.page.db.get_chat_messages(employee_id)
        if page is None:
            self._error("No connection to the server.")
            page = {"messages": [], "has_more": False}
        self.has_more = page["has_more"]
        for message in page["messages"]:
            self._append(message)
        self._sync()
        self.set_enabled(can_write)
        self.scroll_to_end()
        self.mark_read()

    def last_id(self):
        return max(self.bubbles) if self.bubbles else None

    def _sync(self):
        self.earlier_button.setVisible(self.has_more)
        self.empty.setVisible(not self.bubbles)

    # ------------------------------------------------------------------ messages
    def _bubble(self, message):
        mine = str(message["sender_id"]) == self.page.user_id
        self.page.remember_name(message)
        return Bubble(message, mine, message.get("sender_name") or self.page.name_of(message["sender_id"]))

    def _row(self, bubble):
        row = QHBoxLayout()
        if bubble.mine:
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)
        return row

    def _append(self, message):
        if message["id"] in self.bubbles:
            self.bubbles[message["id"]].update_message(**message)
            return False
        bubble = self._bubble(message)
        self.bubbles[message["id"]] = bubble
        self.rows.addLayout(self._row(bubble))
        return True

    def add_live(self, message):
        """A message pushed live or found by polling."""
        if str(message["employee_id"]) != str(self.employee_id):
            return False
        added = self._append(message)
        self._sync()
        if added:
            self.scroll_to_end()
            if str(message["sender_id"]) != self.page.user_id:
                self.typing_label.setText("")
                self.mark_read()
        return added

    def load_earlier(self):
        first = min(self.bubbles) if self.bubbles else None
        page = self.page.db.get_chat_messages(self.employee_id, before_id=first)
        if page is None:
            self._error("No connection to the server.")
            return
        for index, message in enumerate(page["messages"]):
            if message["id"] not in self.bubbles:
                bubble = self._bubble(message)
                self.bubbles[message["id"]] = bubble
                self.rows.insertLayout(index, self._row(bubble))
        self.has_more = page["has_more"]
        self._sync()

    def catch_up(self):
        """Polling fallback: fetch anything newer than what is shown."""
        if self.employee_id is None:
            return
        page = self.page.db.get_chat_messages(self.employee_id, after_id=self.last_id())
        for message in (page or {}).get("messages", []):
            self.add_live(message)

    def apply_state(self, message_ids, **changes):
        for message_id in message_ids:
            bubble = self.bubbles.get(message_id)
            if bubble is not None:
                bubble.update_message(**changes)

    def mark_read(self):
        """Tell the server the other side's messages shown here are read (only if the page is in view)."""
        if self.employee_id is None or not self.page.isVisible():
            return
        theirs = [i for i, b in self.bubbles.items() if not b.mine and not b.message.get("read_at")]
        if theirs and self.page.db.mark_chat_read(self.employee_id, max(theirs)):
            for message_id in theirs:
                self.bubbles[message_id].message["read_at"] = datetime.now().astimezone().isoformat()
            self.page.unread_changed_soon()

    def show_typing(self, user_id):
        self.typing_label.setText(f"{self.page.name_of(user_id) or 'Someone'} is typing…")
        self._typing_clear.start(TYPING_SHOW_MS)

    def scroll_to_end(self):
        # a bound method of this widget: Qt drops the call if the widget is gone by then
        QTimer.singleShot(0, self._to_end)

    def _to_end(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------ writing
    def _on_text_changed(self):
        length = len(self.input.toPlainText())
        if length > MAX_CHARS:
            self._error(f"{length} / {MAX_CHARS} characters — too long to send.")
        elif self.status.isVisible() and "characters" in self.status.text():
            self.status.setVisible(False)
        now = time.monotonic()
        if length and now - self._last_typing_sent > TYPING_SEND_MS / 1000 and self.employee_id is not None:
            self._last_typing_sent = now
            self.page.send_typing(self.employee_id)

    def send(self):
        text = self.input.toPlainText().strip()
        if not text or self.employee_id is None:
            return
        if len(text) > MAX_CHARS:
            self._error(f"A message can have at most {MAX_CHARS} characters.")
            return
        ok, result = self.page.db.send_chat_message(self.employee_id, text)
        if not ok:
            self._error(str(result))                    # the text stays in the box to try again
            return
        self.status.setVisible(False)
        self.input.clear()
        self.add_live(result)
        self.sent.emit()

    def _error(self, text):
        self.status.setText(text)
        self.status.setVisible(True)


class MessagesScreen(QWidget):
    """The Messages page for both roles."""

    #: the number of unread messages for this user changed (the shell updates the badge)
    unread_changed = pyqtSignal(int)

    def __init__(self, user=None, db=None, parent=None, start_socket=True):
        super().__init__(parent)
        self.user = user or {"id": None, "full_name": "", "role": "employee"}
        self.db = db
        self.user_id = str(self.user.get("id")) if self.user.get("id") is not None else None
        self.is_manager = self.user.get("role") == "manager"
        self.conversations = []
        self._names = {self.user_id: self.user.get("full_name", "")}
        self.socket = None
        self._build_ui()
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_MS)
        self.poll_timer.timeout.connect(self._poll)
        self._unread_timer = QTimer(self)
        self._unread_timer.setSingleShot(True)
        self._unread_timer.setInterval(300)
        self._unread_timer.timeout.connect(self.refresh_unread)
        if start_socket and self._online():
            from cloud.chat_socket import ChatSocket
            self.socket = ChatSocket(self.db.api, self)
            self.socket.event_received.connect(self.on_event)
            self.socket.connected_changed.connect(self._on_connection)
            self.socket.start()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        root.setSpacing(theme.SP_3)
        heading = QLabel("Messages")
        heading.setObjectName("H1")
        root.addWidget(heading)
        lead = QLabel("Private conversations with each employee. Only you and the other managers can read them."
                      if self.is_manager else
                      "A private chat with your manager. Other employees cannot see it.")
        lead.setObjectName("LeadLabel")
        lead.setWordWrap(True)
        root.addWidget(lead)
        self.notice = QLabel("")
        self.notice.setObjectName("ErrorLabel")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        root.addWidget(self.notice)
        self.live_label = QLabel("")
        self.live_label.setObjectName("MutedLabel")
        root.addWidget(self.live_label)

        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)
        body = QHBoxLayout(card)
        body.setContentsMargins(theme.SP_4, theme.SP_4, theme.SP_4, theme.SP_4)
        body.setSpacing(theme.SP_4)
        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("ChatList")
        self.conversation_list.setFixedWidth(280)
        self.conversation_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.conversation_list.setTextElideMode(Qt.ElideRight)
        self.conversation_list.currentRowChanged.connect(self._on_conversation_selected)
        self.conversation_list.setVisible(self.is_manager)
        body.addWidget(self.conversation_list)
        self.chat = ChatView(self)
        self.chat.sent.connect(self._on_sent)
        body.addWidget(self.chat, 1)
        root.addWidget(card, 1)

    def _online(self):
        return self.db is not None and getattr(self.db, "api", None) is not None

    def name_of(self, user_id):
        return self._names.get(str(user_id), "")

    def remember_name(self, message):
        if message.get("sender_name"):
            self._names[str(message["sender_id"])] = message["sender_name"]

    # ------------------------------------------------------------------ data
    def refresh(self):
        if not self._online():
            self.notice.setText(ONLINE_ONLY)
            self.notice.setVisible(True)
            self.chat.set_enabled(False)
            return
        self.notice.setVisible(False)
        if self.is_manager:
            self._fill_conversations(keep=self.chat.employee_id)
        elif self.chat.employee_id is None:
            self.chat.open(self.user_id, "Your manager", "Messages go to every manager of your company.")
        else:
            self.chat.catch_up()
            self.chat.mark_read()
        self.poll_timer.setInterval(POLL_MS)
        self._update_polling()
        self.refresh_unread()

    def _fill_conversations(self, keep=None):
        self.conversations = self.db.get_chat_conversations()
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        selected = 0
        for index, conv in enumerate(self.conversations):
            self._names[str(conv["employee_id"])] = conv["employee_name"]
            item = QListWidgetItem(self._conversation_text(conv))
            item.setData(Qt.UserRole, str(conv["employee_id"]))
            self.conversation_list.addItem(item)
            if keep is not None and str(conv["employee_id"]) == str(keep):
                selected = index
        self.conversation_list.blockSignals(False)
        if self.conversations:
            self.conversation_list.setCurrentRow(selected)
            if keep is None or str(self.chat.employee_id) != str(self.conversations[selected]["employee_id"]):
                self._on_conversation_selected(selected)
            else:
                self.chat.catch_up()
                self.chat.mark_read()
        else:
            self.chat.title.setText("No employees yet")
            self.chat.set_enabled(False)

    @staticmethod
    def _conversation_text(conv):
        unread = f"   ({conv['unread']} new)" if conv["unread"] else ""
        last = conv.get("last_message")
        preview = (last["body"].replace("\n", " ")[:42] + ("…" if len(last["body"]) > 42 else "")) if last else \
            "No messages yet"
        status = "  · disabled" if conv.get("employee_status") == "disabled" else ""
        return f"{conv['employee_name']}{unread}{status}\n{preview}"

    def _on_conversation_selected(self, row):
        if row < 0 or row >= len(self.conversations):
            return
        conv = self.conversations[row]
        self.chat.open(str(conv["employee_id"]), conv["employee_name"],
                       "Only managers and this employee can read this conversation.",
                       can_write=conv.get("employee_status") != "disabled")
        conv["unread"] = 0
        self.conversation_list.item(row).setText(self._conversation_text(conv))

    def refresh_unread(self):
        if self._online():
            self.unread_changed.emit(self.db.count_unread_chat())

    def unread_changed_soon(self):
        self._unread_timer.start()

    # ------------------------------------------------------------------ live events
    def on_event(self, event):
        kind = event.get("type")
        if kind == "message":
            message = event["message"]
            shown = self.chat.add_live(message)
            if self.is_manager and not shown:
                self._bump_conversation(message)
            self.unread_changed_soon()
        elif kind == "read":
            self.chat.apply_state(event.get("message_ids", []), read_at=event.get("at"))
            self.unread_changed_soon()
        elif kind == "delivered":
            self.chat.apply_state(event.get("message_ids", []), delivered_at=event.get("at"))
        elif kind == "typing":
            if str(event.get("employee_id")) == str(self.chat.employee_id):
                self.chat.show_typing(event.get("user_id"))

    def _bump_conversation(self, message):
        for row, conv in enumerate(self.conversations):
            if str(conv["employee_id"]) == str(message["employee_id"]):
                if str(message["sender_id"]) != self.user_id:
                    conv["unread"] = conv.get("unread", 0) + 1
                conv["last_message"] = message
                self.conversation_list.item(row).setText(self._conversation_text(conv))
                return
        self._fill_conversations(keep=self.chat.employee_id)       # a conversation that was not listed yet

    def send_typing(self, employee_id):
        if self.socket is not None:
            self.socket.typing(employee_id)

    def _on_sent(self):
        if self.is_manager:
            for row, conv in enumerate(self.conversations):
                if str(conv["employee_id"]) == str(self.chat.employee_id):
                    conv["last_message"] = self.chat.bubbles[self.chat.last_id()].message
                    self.conversation_list.item(row).setText(self._conversation_text(conv))

    def _on_connection(self, connected):
        self.live_label.setText("● Live" if connected else "○ Reconnecting… (checking for new messages every few seconds)")
        self._update_polling()
        if connected:
            self.chat.catch_up()                                 # anything missed while disconnected

    def _update_polling(self):
        live = self.socket is not None and self.socket.connected
        if self._online() and not live and self.isVisible():
            self.poll_timer.start()
        else:
            self.poll_timer.stop()

    def _poll(self):
        if not self.isVisible():
            self.poll_timer.stop()
            return
        if self.is_manager:
            self._fill_conversations(keep=self.chat.employee_id)
        else:
            self.chat.catch_up()
        self.refresh_unread()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_polling()

    def shutdown(self):
        """Close the live channel (sign-out)."""
        self.poll_timer.stop()
        if self.socket is not None:
            self.socket.stop()
