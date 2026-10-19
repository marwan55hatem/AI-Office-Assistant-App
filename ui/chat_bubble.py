"""One chat message as a rounded bubble.

The user's messages are plain text.  The assistant's are shown with a little
Markdown: paragraphs / lists / **bold** as rich text, and code blocks as their own
monospace box with a Copy button.  The bubble always keeps the *raw* text
(:meth:`ChatBubble.text`), which is what gets stored in the database.
"""

from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui import markdown, theme

MAX_TEXT_WIDTH = 560       # widest line of text inside a bubble
COPIED_MS = 1500           # how long the Copy button says "Copied"


def format_timestamp(value):
    """``"14:05"`` for today, ``"Oct 13, 14:05"`` for another day.

    ``value`` is a ``'YYYY-MM-DD HH:MM:SS'`` string from the database, a
    ``datetime``, or None (meaning "now").
    """
    if value is None:
        stamp = datetime.now()
    elif isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return str(value)
    if stamp.date() == datetime.now().date():
        return stamp.strftime("%H:%M")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return "%s %d, %s" % (months[stamp.month - 1], stamp.day, stamp.strftime("%H:%M"))


class _CodeText(QPlainTextEdit):
    """Read-only, never wraps; the mouse wheel scrolls the chat, not this box."""

    def wheelEvent(self, event):
        if event.angleDelta().x():
            super().wheelEvent(event)           # sideways scrolling of a long line
        else:
            event.ignore()                      # let the chat scroll


class CodeBlock(QFrame):
    """A code block: language name, Copy button and the code in a monospace box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CodeBlock")
        self.code = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SP_3, theme.SP_2, theme.SP_3, theme.SP_2)
        layout.setSpacing(theme.SP_1)

        header = QHBoxLayout()
        self.lang_label = QLabel("code")
        self.lang_label.setObjectName("CodeLang")
        header.addWidget(self.lang_label)
        header.addStretch(1)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("CodeCopyButton")
        self.copy_button.setCursor(Qt.PointingHandCursor)
        self.copy_button.setFocusPolicy(Qt.NoFocus)
        self.copy_button.setFixedHeight(26)
        self.copy_button.clicked.connect(self.copy)
        header.addWidget(self.copy_button)
        layout.addLayout(header)

        self.editor = _CodeText()
        self.editor.setObjectName("CodeText")
        self.editor.setReadOnly(True)
        self.editor.setFrameShape(QFrame.NoFrame)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self.editor)

    def set_code(self, lang, code):
        """Show ``code`` (language label ``lang``) and resize the box to fit."""
        self.lang_label.setText(lang or "code")
        if code != self.code:
            self.code = code
            self.editor.setPlainText(code)
        self._fit()

    def copy(self):
        """Copy the code (only the code, not the language name) to the clipboard."""
        QApplication.clipboard().setText(self.code)
        self.copy_button.setText("Copied ✓")
        QTimer.singleShot(COPIED_MS, lambda: self.copy_button.setText("Copy"))

    def _fit(self):
        """Make the box exactly as tall as its lines (plus the sideways scrollbar if needed)."""
        metrics = self.editor.fontMetrics()
        lines = self.code.count("\n") + 1
        height = lines * metrics.lineSpacing() + 2 * int(self.editor.document().documentMargin()) + 2
        width = self.editor.viewport().width()
        if width > 60:
            longest = max((metrics.horizontalAdvance(line.replace("\t", "    ")) for line in self.code.split("\n")), default=0)
            if longest + 2 * self.editor.document().documentMargin() > width:
                height += self.editor.horizontalScrollBar().sizeHint().height()
        self.editor.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class ChatBubble(QFrame):
    """A message bubble.  The user's is accent-tinted, the assistant's is a surface.

    The row that holds the bubble decides the alignment (user right, assistant
    left); the bubble itself only knows its role.  ``append_text`` lets the
    assistant's bubble grow while the reply is "typed".
    """

    def __init__(self, role, content="", timestamp=None, parent=None):
        super().__init__(parent)
        self.role = role
        self.setObjectName("ChatBubbleUser" if role == "user" else "ChatBubbleAssistant")
        self._natural_width = 0
        self._limit = MAX_TEXT_WIDTH
        self.thinking = False
        self._raw = ""
        self._parts = []                # [(kind, widget)] currently shown

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SP_4, theme.SP_3, theme.SP_4, theme.SP_2)
        layout.setSpacing(theme.SP_1)

        self._body = QWidget()
        self._body.setObjectName("ChatBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(theme.SP_2)
        layout.addWidget(self._body)

        self.set_text(content)
        self.reserve_width(content)

        self.time_label = QLabel(format_timestamp(timestamp))
        self.time_label.setObjectName("ChatTime")
        self.time_label.setAlignment(Qt.AlignRight if role == "user" else Qt.AlignLeft)
        layout.addWidget(self.time_label)

    # ------------------------------------------------------------------ width
    def reserve_width(self, full_text):
        """Size the bubble for ``full_text`` (a reply that will be typed in later,
        so the bubble does not keep changing width while it fills up)."""
        metrics = self.fontMetrics()
        longest = max((metrics.horizontalAdvance(line) for line in str(full_text).split("\n")), default=0)
        self._natural_width = longest + 4
        self._apply_width()

    def reserve_full_width(self):
        """Use the widest allowed text line (a reply whose length is not known yet)."""
        self._natural_width = 10 ** 6
        self._apply_width()

    def set_width_limit(self, limit):
        """Never let the text line be wider than ``limit`` pixels (window size)."""
        self._limit = max(160, int(limit))
        self._apply_width()

    def _apply_width(self):
        width = min(self._natural_width, self._limit)
        # a word-wrapped QLabel otherwise picks a narrow default width
        self._body.setMinimumWidth(width)
        self._body.setMaximumWidth(max(width, self._limit))

    # ------------------------------------------------------------------ content
    def set_thinking(self, thinking):
        """Show the muted, italic "Thinking..." look (until the first text arrives)."""
        self.thinking = bool(thinking)
        for kind, widget in self._parts:
            if kind == "text":
                self._mark_thinking(widget)

    def _mark_thinking(self, label):
        label.setProperty("thinking", "true" if self.thinking else "false")
        theme.repolish(label)

    def text(self):
        """The raw message text shown so far (this is what is stored)."""
        return self._raw

    def set_text(self, text):
        """Replace the whole text."""
        self._raw = str(text)
        self._render()

    def append_text(self, piece):
        """Add a piece of text at the end (streaming)."""
        self._raw += str(piece)
        self._render()

    def code_blocks(self):
        """The :class:`CodeBlock` widgets currently shown."""
        return [widget for kind, widget in self._parts if kind == "code"]

    def _render(self):
        """Bring the shown parts in line with the raw text, reusing widgets where possible."""
        if self.role == "user":
            segments = [markdown.Segment("plain", self._raw, "", True)]
        else:
            segments = markdown.split_segments(self._raw) or [markdown.Segment("text", "", "", True)]
        for index, segment in enumerate(segments):
            kind = "code" if segment.kind == "code" else "text"
            if index < len(self._parts) and self._parts[index][0] != kind:
                self._drop_parts(index)
            if index >= len(self._parts):
                widget = self._new_part(kind)
                self._parts.append((kind, widget))
                self._body_layout.addWidget(widget)
            widget = self._parts[index][1]
            if kind == "code":
                widget.set_code(segment.lang, segment.text)
            elif segment.kind == "plain":
                if widget.text() != segment.text:
                    widget.setText(segment.text)
            else:
                html_text = markdown.to_html(segment.text)
                if widget.text() != html_text:
                    widget.setText(html_text)
        self._drop_parts(len(segments))

    def _drop_parts(self, keep):
        for _kind, widget in self._parts[keep:]:
            self._body_layout.removeWidget(widget)
            widget.deleteLater()
        del self._parts[keep:]

    def _new_part(self, kind):
        if kind == "code":
            return CodeBlock()
        label = QLabel()
        label.setObjectName("ChatText")
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText if self.role == "user" else Qt.RichText)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setOpenExternalLinks(False)
        self._mark_thinking(label)
        return label
