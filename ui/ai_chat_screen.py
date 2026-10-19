"""AI Chat: talk to the local assistant (chat list on the left, conversation on the right).

The assistant lives in ``assistant/answers.py`` and answers from the local
database; this screen only shows the conversation.  A reply is computed at once
(on this thread, where the database is) and then "typed" into the bubble piece by
piece by a timer -- no worker thread is needed, so nothing can outlive the screen.
"""

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import pyqtSignal

from chat.chat_client import ChatClient
from llm.service import ModelService
from llm import status as model_status
from ui import preferences, theme
from ui.chat_bubble import ChatBubble, format_timestamp

STREAM_INTERVAL_MS = 25        # how often the next piece of a reply appears
THINK_MS = 450                 # the "Thinking..." pause before a reply starts to appear
THINK_FRAME_MS = 150
BADGE_MS = 2000                # how often the "AI model" badge is refreshed
IDLE_CHECK_MS = 60000         # how often to check whether the language model can be unloaded
BOTTOM_TOLERANCE = 12          # px from the bottom that still counts as "at the bottom"
MAX_INPUT_LINES = 4
LIST_WIDTH = 300

WELCOME = (
    "Hi, I'm your local task assistant. I can list your tasks and deadlines, help you "
    "plan how to tackle a task, and tell you about your calendar and focus time"
    "%s. Everything stays on this computer. What would you like to know?"
)
WELCOME_MANAGER = ", and your team's performance"

#: One-click questions shown in a new / empty chat.
SUGGESTIONS = [
    "What tasks do I have?", "What should I do first?",
    "What's due soon?", "What's on my calendar today?",
]
SUGGESTIONS_MANAGER = [
    "How is the team doing today?", "Who is the best performer?",
    "Who should I check in on?", "Summarize last week's performance",
]


class ChatInput(QPlainTextEdit):
    """Message box: Enter sends, Shift+Enter starts a new line; grows up to 4 lines."""

    submitted = pyqtSignal()
    history_up = pyqtSignal()
    history_down = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.recalling = False          # the text is an earlier message brought back with Up
        self._programmatic = False
        self.setObjectName("ChatInput")
        self.setPlaceholderText("Type a message…  (Enter sends, Shift+Enter = new line)")
        # the global input rule has min-height: 24px; the height is managed below
        self.setStyleSheet("min-height: 0px;")
        self.textChanged.connect(self._fit_height)
        self.textChanged.connect(self._on_text_changed)
        self._fit_height()

    def _on_text_changed(self):
        if not self._programmatic:
            self.recalling = False      # the user typed: no longer "browsing history"

    def set_recalled(self, text):
        """Put an earlier message into the box (Up / Down browsing)."""
        self._programmatic = True
        self.setPlainText(text)
        self.moveCursor(self.textCursor().End)
        self._programmatic = False
        self.recalling = bool(text)

    def keyPressEvent(self, event):
        key, plain = event.key(), not event.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        if plain and key == Qt.Key_Up and (not self.toPlainText() or self.recalling):
            self.history_up.emit()      # Up on an empty box brings back the last message
            return
        if plain and key == Qt.Key_Down and self.recalling:
            self.history_down.emit()
            return
        super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_height()          # the real font is known only once the widget is shown

    def _fit_height(self):
        line = self.fontMetrics().lineSpacing()
        # a plain-text document reports its height in *lines* (wrapped ones included)
        total = int(self.document().size().height())
        lines = max(1, min(MAX_INPUT_LINES, total))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if total > MAX_INPUT_LINES else Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(lines * line + 34)          # + padding of the global input style


class ChatListItem(QWidget):
    """Title, last message and time of one chat in the list."""

    WIDTH = LIST_WIDTH - 12

    def __init__(self, chat, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SP_3, theme.SP_2, theme.SP_3, theme.SP_2)
        layout.setSpacing(2)

        title = QLabel(chat.title)
        title.setObjectName("ChatItemTitle")
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(title)

        snippet = QLabel()
        snippet.setObjectName("ChatItemSnippet")
        snippet.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text = " ".join(chat.last_message.replace("```", " ").replace("**", "").split()) if chat.message_count else "No messages yet"
        snippet.setText(snippet.fontMetrics().elidedText(text, Qt.ElideRight, self.WIDTH - 2 * theme.SP_3 - 8))
        layout.addWidget(snippet)

        stamp = QLabel(format_timestamp(chat.updated_at))
        stamp.setObjectName("ChatItemTime")
        layout.addWidget(stamp)
        for label in (title, snippet, stamp):
            label.setTextFormat(Qt.PlainText)
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)


class AIChatScreen(QWidget):
    """The AI Chat page of both shells."""

    def __init__(self, user=None, db=None, parent=None, client=None, model_service=None):
        """``client`` (chat storage + assistant) and ``model_service`` (the language model)
        can be injected; by default they are built from ``db`` and the local model."""
        super().__init__(parent)
        self.user = user or {"id": 2, "full_name": "Marwan Hatem", "role": "employee"}
        self.db = db
        if client is None and db is not None and self.user.get("id"):
            client = ChatClient(db, self.user["id"])
        self.client = client
        self.models = model_service if model_service is not None else ModelService()

        self.current_chat_id = None
        self._first_open_done = False
        self._generating = False
        self._chunks = None
        self._bubble = None
        self._stick_to_bottom = True      # follow new text unless the user scrolled up
        self._history_index = None

        self._timer = QTimer(self)
        self._timer.setInterval(STREAM_INTERVAL_MS)
        self._timer.timeout.connect(self._pump)
        # "Thinking..." before a reply starts
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.setInterval(THINK_MS)
        self._start_timer.timeout.connect(self._begin_stream)
        self._think_timer = QTimer(self)
        self._think_timer.setInterval(THINK_FRAME_MS)
        self._think_timer.timeout.connect(self._think_frame)
        self._think_dots = 0
        self._think_label = "Thinking"
        # language model (general questions): a background worker writes the reply
        self._reply = None                # the ReplyStream being shown
        self._worker = None               # LoadWorker / GenerateWorker of the current reply
        self._idle_timer = QTimer(self)   # frees the GPU memory when the model is not used
        self._idle_timer.setInterval(IDLE_CHECK_MS)
        self._idle_timer.timeout.connect(self._unload_idle_model)
        self._idle_timer.start()
        self._loading = False             # the model is being loaded right now
        self._badge_timer = QTimer(self)  # keeps the "AI model" badge in the header up to date
        self._badge_timer.setInterval(BADGE_MS)
        self._badge_timer.timeout.connect(self._update_model_badge)
        self._badge_timer.start()

        self._build_ui()
        self._set_shortcuts()
        self._update_model_badge()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        root.setSpacing(theme.SP_4)
        root.addWidget(self._build_left(), 0)
        root.addWidget(self._build_right(), 1)

    def _build_left(self):
        column = QWidget()
        column.setFixedWidth(LIST_WIDTH)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_3)

        self.new_chat_button = QPushButton("+  New Chat")
        self.new_chat_button.setObjectName("PrimaryButton")
        self.new_chat_button.setCursor(Qt.PointingHandCursor)
        self.new_chat_button.setStyleSheet("min-height: 0px;")
        self.new_chat_button.setFixedHeight(48)
        self.new_chat_button.clicked.connect(self._on_new_chat)
        layout.addWidget(self.new_chat_button)

        self.chat_list = QListWidget()
        self.chat_list.setObjectName("ChatList")
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self._on_list_menu)
        self.chat_list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self.chat_list, 1)

        self.list_hint = QLabel("No chats yet. Click + New Chat.")
        self.list_hint.setObjectName("EmptyLabel")
        self.list_hint.setWordWrap(True)
        self.list_hint.setAlignment(Qt.AlignCenter)
        self.list_hint.setVisible(False)
        layout.addWidget(self.list_hint)
        return column

    def _build_right(self):
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, theme.SP_4)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("Navbar")
        header.setFixedHeight(theme.NAVBAR_HEIGHT)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(theme.SP_5, 0, theme.SP_5, 0)
        self.chat_title = QLabel("AI Chat")
        self.chat_title.setObjectName("H3")
        header_row.addWidget(self.chat_title)
        header_row.addStretch(1)
        self.model_badge = QLabel("")
        self.model_badge.setObjectName("ModelBadge")
        self.model_badge.setProperty("state", "idle")
        self.model_badge.setToolTip("Questions about your tasks, calendar and team are answered from your data. "
                                    "General questions use a small AI model that runs on this computer.")
        header_row.addWidget(self.model_badge)
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("ScrollContent")
        self.messages = QVBoxLayout(content)
        self.messages.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        self.messages.setSpacing(theme.SP_3)
        self.empty_label = QLabel("No messages yet. Ask me about your tasks, deadlines or calendar.")
        self.empty_label.setObjectName("EmptyLabel")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.messages.addWidget(self.empty_label)
        self.messages.addStretch(1)
        self.scroll.setWidget(content)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        layout.addWidget(self.scroll, 1)

        # one-click starter questions (only in a chat that has no question yet)
        self.suggestions = QWidget()
        grid = QGridLayout(self.suggestions)
        grid.setContentsMargins(theme.SP_5, theme.SP_3, theme.SP_5, 0)
        grid.setHorizontalSpacing(theme.SP_2)
        grid.setVerticalSpacing(theme.SP_2)
        self.suggestion_buttons = []
        questions = SUGGESTIONS_MANAGER if self.user.get("role") == "manager" else SUGGESTIONS
        for index, question in enumerate(questions):
            button = QPushButton(question)
            button.setObjectName("GhostButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet("min-height: 0px; padding: 6px 12px; font-size: 13px;")
            button.setFixedHeight(36)
            button.clicked.connect(lambda _checked=False, q=question: self._ask(q))
            grid.addWidget(button, index // 2, index % 2)
            self.suggestion_buttons.append(button)
        layout.addWidget(self.suggestions)

        bar = QHBoxLayout()
        bar.setContentsMargins(theme.SP_5, theme.SP_3, theme.SP_5, 0)
        bar.setSpacing(theme.SP_3)
        self.input = ChatInput()
        self.input.submitted.connect(self._on_send)
        self.input.history_up.connect(lambda: self._history_move(-1))
        self.input.history_down.connect(lambda: self._history_move(1))
        bar.addWidget(self.input, 1, Qt.AlignBottom)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setMinimumWidth(120)
        self.send_button.setStyleSheet("min-height: 0px;")
        self.send_button.setFixedHeight(52)
        self.send_button.clicked.connect(self._on_send_clicked)
        bar.addWidget(self.send_button, 0, Qt.AlignBottom)
        layout.addLayout(bar)
        return card

    def _set_shortcuts(self):
        self.shortcut_new = QShortcut(QKeySequence("Ctrl+N"), self, activated=self._on_new_chat)
        self.shortcut_focus = QShortcut(QKeySequence("Ctrl+L"), self, activated=self.input.setFocus)

    # ------------------------------------------------------------------ #
    #  Chat list
    # ------------------------------------------------------------------ #
    def refresh(self):
        """Reload the chat list (the shell calls this whenever the page is opened)."""
        self._update_model_badge()
        if self.client is None or self._generating:
            return
        chats = self.client.list_chats()
        if not chats and not self._first_open_done:
            self._first_open_done = True
            chat = self.client.new_chat()
            self.client.save_reply(chat.id, self._welcome_text())
            self.current_chat_id = chat.id
        self._first_open_done = True
        self._reload_list(self.current_chat_id)

    def _welcome_text(self):
        return WELCOME % (WELCOME_MANAGER if self.user.get("role") == "manager" else "")

    def _reload_list(self, select_id=None):
        chats = self.client.list_chats()
        self.chat_list.blockSignals(True)
        self.chat_list.clear()
        selected_row = -1
        for row, chat in enumerate(chats):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, chat.id)
            widget = ChatListItem(chat)
            item.setSizeHint(widget.sizeHint())
            self.chat_list.addItem(item)
            self.chat_list.setItemWidget(item, widget)
            if chat.id == select_id:
                selected_row = row
        if selected_row < 0 and chats:
            selected_row = 0
        if selected_row >= 0:
            self.chat_list.setCurrentRow(selected_row)
        self.chat_list.blockSignals(False)
        self.list_hint.setVisible(not chats)

        wanted = chats[selected_row].id if selected_row >= 0 else None
        if wanted is not None and wanted == self.current_chat_id:
            self.chat_title.setText(chats[selected_row].title)     # renamed / auto-titled
        if wanted != self.current_chat_id or self._view_is_stale(wanted):
            self._open_chat(wanted)

    def _view_is_stale(self, chat_id):
        """The bubbles on screen belong to another chat (or nothing is shown yet)."""
        return chat_id is not None and getattr(self, "_shown_chat_id", None) != chat_id

    def _on_item_changed(self, item, _previous):
        if item is None or self._generating:
            return
        chat_id = item.data(Qt.UserRole)
        if chat_id != self.current_chat_id:
            self._open_chat(chat_id)

    def _on_list_menu(self, position):
        item = self.chat_list.itemAt(position)
        if item is None or self._generating:
            return
        chat_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        rename = menu.addAction("Rename")
        delete = menu.addAction("Delete")
        chosen = menu.exec_(self.chat_list.viewport().mapToGlobal(position))
        if chosen is rename:
            self.rename_chat(chat_id)
        elif chosen is delete:
            self.delete_chat(chat_id)

    def rename_chat(self, chat_id):
        """Ask for a new title and apply it."""
        current = next((c.title for c in self.client.list_chats() if c.id == chat_id), "")
        title, accepted = QInputDialog.getText(self, "Rename chat", "New title:", text=current)
        if not accepted or not title.strip():
            return
        self.client.rename_chat(chat_id, title)
        self._reload_list(self.current_chat_id)

    def delete_chat(self, chat_id):
        """Delete a chat after a confirmation."""
        answer = QMessageBox.question(
            self, "Delete chat", "Delete this chat and all its messages?",
            QMessageBox.Cancel | QMessageBox.Yes, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        self.client.delete_chat(chat_id)
        if chat_id == self.current_chat_id:
            self.current_chat_id = None
            self._shown_chat_id = None
        self._reload_list(self.current_chat_id)
        if self.current_chat_id is None:
            self._open_chat(None)

    def _on_new_chat(self):
        if self.client is None or self._generating:
            return
        chat = self.client.new_chat()
        self._reload_list(chat.id)
        self.input.setFocus()

    # ------------------------------------------------------------------ #
    #  Conversation view
    # ------------------------------------------------------------------ #
    def _clear_bubbles(self):
        for index in reversed(range(self.messages.count())):
            item = self.messages.itemAt(index)
            widget = item.widget()
            if widget is not None and widget is not self.empty_label:
                widget.setParent(None)
                widget.deleteLater()

    def _open_chat(self, chat_id):
        """Show one chat's history."""
        self.current_chat_id = chat_id
        self._shown_chat_id = chat_id
        self._clear_bubbles()
        title = "AI Chat"
        count = 0
        if chat_id is not None and self.client is not None:
            row = next((c for c in self.client.list_chats() if c.id == chat_id), None)
            title = row.title if row else title
            for message in self.client.get_messages(chat_id):
                self._add_bubble(message.role, message.content, message.created_at)
                count += 1
        self.chat_title.setText(title)
        self.empty_label.setVisible(count == 0)
        self._history_index = None
        self._scroll_to_bottom(force=True)
        self._update_suggestions()

    def _add_bubble(self, role, text, timestamp=None):
        """Append a bubble row (user on the right, assistant on the left)."""
        bubble = ChatBubble(role, text, timestamp)
        bubble.set_width_limit(self._text_limit())
        row = QWidget()
        row.setObjectName("ScrollContent")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            layout.addStretch(1)
            layout.addWidget(bubble, 0, Qt.AlignTop)
        else:
            layout.addWidget(bubble, 0, Qt.AlignTop)
            layout.addStretch(1)
        self.messages.insertWidget(self.messages.count() - 1, row)
        self.empty_label.setVisible(False)
        return bubble

    def _text_limit(self):
        """Widest text line a bubble may have in the current window."""
        return int(self.scroll.viewport().width() * 0.72) - 60

    def resizeEvent(self, event):
        super().resizeEvent(event)
        limit = self._text_limit()
        for bubble in self.findChildren(ChatBubble):
            bubble.set_width_limit(limit)

    def _on_scrolled(self, value):
        """Remember whether the user is reading further up (then new text must not yank the view)."""
        bar = self.scroll.verticalScrollBar()
        self._stick_to_bottom = value >= bar.maximum() - BOTTOM_TOLERANCE

    def _scroll_to_bottom(self, force=False):
        """Scroll down to the newest text -- unless the user scrolled up on purpose."""
        if force:
            self._stick_to_bottom = True
        if not self._stick_to_bottom:
            return
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    # ------------------------------------------------------------------ #
    #  Sending and "typing" the reply
    # ------------------------------------------------------------------ #
    def _on_send_clicked(self):
        if self._generating:
            self.stop_generation()
        else:
            self._on_send()

    def _ask(self, text):
        """Send ``text`` as if it had been typed (the suggestion buttons use this)."""
        if self._generating:
            return
        self.input.setPlainText(text)
        self._on_send()

    def _on_send(self):
        if self._generating or self.client is None:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self._history_index = None
        if self.current_chat_id is None:
            self.current_chat_id = self.client.new_chat().id
            self._shown_chat_id = self.current_chat_id
        chat_id = self.current_chat_id

        message = self.client.send_message(chat_id, text)
        self._add_bubble("user", message.content)
        self.input.clear()
        self.input.recalling = False

        self._sync_model_setting()
        reply = self.client.stream_reply(chat_id, delay=0)
        self._reply = reply
        self._chunks = iter(reply)
        self._bubble = self._add_bubble("assistant", "")
        if reply.kind == "llm":
            self._bubble.reserve_full_width()       # the model's text is not known yet
        else:
            self._bubble.reserve_width(reply.full_text)
        self._set_generating(True)
        self._scroll_to_bottom(force=True)
        self._bubble.set_thinking(True)
        self._think_dots = 0
        self._think_label = "Thinking"
        self._think_frame()
        self._think_timer.start()
        if reply.kind == "llm":
            self._start_llm(reply)
        else:
            self._start_timer.start()

    # ---------------------------------------------------------------- language model
    def _start_llm(self, reply):
        """General question: load the model if needed, then let it write the answer."""
        if self.models.is_loaded():
            self._think_label = self._thinking_label(self.models.device())
            self._run_generation(reply)
            return
        self._think_label = "Loading the assistant model"
        self._loading = True
        worker = self.models.create_load_worker(self)
        worker.loaded.connect(lambda device, w=worker: self._on_model_loaded(w, device))
        worker.failed.connect(lambda message, w=worker: self._on_llm_failed(w, message))
        worker.finished.connect(self._on_load_finished)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        self._update_model_badge()
        worker.start()

    @staticmethod
    def _thinking_label(device):
        """CPU mode is much slower: say so while the user waits."""
        return "Thinking (CPU mode — this can take a minute)" if device == "cpu" else "Thinking"

    def _on_load_finished(self):
        self._loading = False             # also when the load was stopped or failed
        self._update_model_badge()

    def _on_model_loaded(self, worker, device="cuda"):
        if worker is not self._worker or self._reply is None:       # stopped meanwhile
            return
        self._think_label = self._thinking_label(device)
        self._run_generation(self._reply)

    def _run_generation(self, reply):
        worker = self.models.create_generate_worker(reply.messages, self)
        worker.piece.connect(lambda text, w=worker: self._on_llm_piece(w, text))
        worker.done.connect(lambda stopped, w=worker: self._on_llm_done(w, stopped))
        worker.failed.connect(lambda message, w=worker: self._on_llm_failed(w, message))
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_llm_piece(self, worker, text):
        if worker is not self._worker or self._bubble is None:
            return
        if self._bubble.thinking:                  # first words: leave the "Thinking..." look
            self._think_timer.stop()
            self._bubble.set_thinking(False)
            self._bubble.set_text("")
        self._bubble.append_text(text)
        self._scroll_to_bottom()

    def _on_llm_done(self, worker, stopped):
        if worker is not self._worker or not self._generating:
            return
        self._worker = None
        self._finish(stopped=False)

    def _on_llm_failed(self, worker, message):
        """The model could not answer: show the engine's own answer instead."""
        if worker is not self._worker or self._bubble is None:
            return
        self._worker = None
        self._think_timer.stop()
        self._bubble.set_thinking(False)
        self._bubble.set_text(self._reply.fallback_text)
        self._reply.source = "engine"
        self._reply.sources = []                    # the fallback text already names its sources
        self._finish(stopped=False)

    def _sync_model_setting(self):
        """Hand the Settings switch ("use the AI model") to the chat backend."""
        backend = getattr(self.client, "backend", None)
        if backend is not None and hasattr(backend, "llm_enabled"):
            backend.llm_enabled = preferences.model_enabled()

    def _update_model_badge(self):
        """The header badge: is the AI model off / not installed / loading / ready / on CPU?"""
        state, text = model_status.snapshot(preferences.model_enabled(), self._loading)
        if self.model_badge.text() != text:
            self.model_badge.setText(text)
        if self.model_badge.property("state") != state:
            self.model_badge.setProperty("state", state)
            theme.repolish(self.model_badge)

    def _unload_idle_model(self):
        if self._generating:
            return
        self.models.unload_if_idle()

    def _think_frame(self):
        """One frame of the "Thinking..." animation."""
        self._think_dots = self._think_dots % 3 + 1
        if self._bubble is not None and self._bubble.thinking:
            self._bubble.set_text(self._think_label + "." * self._think_dots)

    def _begin_stream(self):
        """The thinking pause is over: start typing the reply."""
        self._think_timer.stop()
        if self._bubble is None:
            return
        self._bubble.set_thinking(False)
        self._bubble.set_text("")
        self._timer.start()

    def _pump(self):
        """Timer slot: put the next piece of the reply into the bubble."""
        try:
            piece = next(self._chunks)
        except StopIteration:
            self._finish(stopped=False)
            return
        self._bubble.append_text(piece)
        self._scroll_to_bottom()

    def stop_generation(self):
        """Stop typing the reply now (what was shown so far is kept)."""
        if self._generating:
            worker, self._worker = self._worker, None      # late signals of it are ignored
            if worker is not None and hasattr(worker, "stop"):
                try:
                    worker.stop()
                except RuntimeError:                        # the thread object is already gone
                    pass
            self._finish(stopped=True)

    def _finish(self, stopped):
        self._timer.stop()
        self._start_timer.stop()
        self._think_timer.stop()
        shown = "" if self._bubble.thinking else self._bubble.text().strip()
        if stopped and shown:
            shown += " … (stopped)"
            self._bubble.set_text(shown)
        elif shown and self._reply is not None and self._reply.sources:
            from llm.prompts import with_sources

            shown = with_sources(shown, self._reply.sources)    # name the documents the answer used
            self._bubble.set_text(shown)
        chat_id = self.current_chat_id
        if shown:
            self._bubble.reserve_width(shown)       # fit the bubble to what was really written
            self.client.save_reply(chat_id, shown, self._reply.source if self._reply else None)
        else:
            self._bubble.parentWidget().deleteLater()
        self.client.auto_title(chat_id)
        self._chunks = None
        self._bubble = None
        self._reply = None
        self._worker = None
        self._set_generating(False)
        self._reload_list(chat_id)
        self.input.setFocus()

    def _set_generating(self, busy):
        self._generating = busy
        self.input.setEnabled(not busy)
        self.chat_list.setEnabled(not busy)
        self.new_chat_button.setEnabled(not busy)
        self._update_suggestions()
        self.send_button.setText("⏹  Stop" if busy else "Send")
        self.send_button.setObjectName("DangerButton" if busy else "PrimaryButton")
        theme.repolish(self.send_button)

    # ------------------------------------------------------------------ #
    #  Starter questions and message history
    # ------------------------------------------------------------------ #
    def _update_suggestions(self):
        """Starter buttons: only while nothing was asked in this chat and nothing is typing."""
        asked = any(b.role == "user" for b in self.findChildren(ChatBubble))
        self.suggestions.setVisible(not asked and not self._generating and self.client is not None)

    def _history_move(self, step):
        """Up / Down in the message box: browse the questions asked in this chat."""
        if self.client is None or self.current_chat_id is None:
            return
        history = [m.content for m in self.client.get_messages(self.current_chat_id) if m.role == "user"]
        if not history:
            return
        if self._history_index is None:
            index = len(history) - 1 if step < 0 else None
        else:
            index = self._history_index + step
        if index is None or index >= len(history):
            self._history_index = None
            self.input.set_recalled("")
            return
        index = max(0, index)
        self._history_index = index
        self.input.set_recalled(history[index])
