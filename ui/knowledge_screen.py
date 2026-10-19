"""Knowledge screen (managers only): the documents the AI Chat can read.

A manager adds ``.txt`` / ``.md`` files (button or drag and drop), chooses who may
read each one -- everyone or managers only -- and can remove them.  The chat then
finds the matching passages (BM25 search) and names the file it used.  A search box
shows exactly what the assistant would find for a question.
"""

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from knowledge.store import MAX_FILE_BYTES, KnowledgeBase, KnowledgeError
from ui import theme
from ui.widgets import make_card

CONTENT_MAX_WIDTH = 1100
HEADERS = ["Document", "Who can read it", "Words", "Size", "Added", ""]
VISIBILITY_LABELS = [("everyone", "Everyone"), ("managers", "Managers only")]
VISIBILITY_COLUMN_WIDTH = 200
REMOVE_COLUMN_WIDTH = 130
FILE_FILTER = "Text and Markdown files (*.txt *.md *.markdown)"


def _size_text(size):
    return "%d KB" % max(1, round(size / 1024)) if size >= 1024 else "%d B" % size


class KnowledgeScreen(QWidget):
    """Manage the assistant's documents."""

    def __init__(self, user=None, db=None, parent=None, kb=None):
        """``kb`` (a :class:`knowledge.store.KnowledgeBase`) can be injected; by default
        one is built on ``db``."""
        super().__init__(parent)
        self.user = user if user is not None else {"id": 1, "full_name": "Admin Manager"}
        self.db = db
        self.kb = kb if kb is not None else (KnowledgeBase(db) if db is not None else None)
        self.setAcceptDrops(True)
        self._last_key = None
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("Navbar")
        header.setFixedHeight(theme.NAVBAR_HEIGHT)
        row = QHBoxLayout(header)
        row.setContentsMargins(theme.SP_6, 0, theme.SP_6, 0)
        title = QLabel("\U0001F4DA  Knowledge")
        title.setObjectName("H3")
        row.addWidget(title)
        row.addStretch(1)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("ScrollContent")
        outer = QHBoxLayout(content)
        outer.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        outer.addStretch(1)
        column = QWidget()
        column.setMaximumWidth(CONTENT_MAX_WIDTH)
        column.setMinimumWidth(520)
        body = QVBoxLayout(column)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(theme.SP_5)
        body.addWidget(self._build_documents_card())
        body.addWidget(self._build_search_card())
        body.addStretch(1)
        outer.addWidget(column, 100)
        outer.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _build_documents_card(self):
        card, layout = make_card(
            "Documents for the AI Chat",
            "Add notes, guides and policies as .txt or .md files (up to %d MB each). The AI Chat "
            "searches them when someone asks a question, quotes the matching passages and names the file. "
            "Everything stays on this computer." % (MAX_FILE_BYTES // 2 ** 20))

        controls = QHBoxLayout()
        controls.setSpacing(theme.SP_3)
        self.add_button = QPushButton("＋  Add documents…")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.setStyleSheet("min-height: 0px;")      # the global button rule would make it tall
        self.add_button.setFixedHeight(48)
        self.add_button.clicked.connect(self._choose_files)
        controls.addWidget(self.add_button)

        who = QLabel("Who can read new documents:")
        who.setObjectName("FieldLabel")
        controls.addWidget(who)
        self.visibility_combo = QComboBox()
        for value, label in VISIBILITY_LABELS:
            self.visibility_combo.addItem(label, value)
        controls.addWidget(self.visibility_combo)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        layout.addWidget(self.status)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for column, width in ((1, VISIBILITY_COLUMN_WIDTH), (5, REMOVE_COLUMN_WIDTH)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)       # cell widgets: fixed room
            self.table.setColumnWidth(column, width)
        layout.addWidget(self.table)

        self.empty_label = QLabel("No documents yet.\nClick “Add documents…” (or drop .txt / .md files here) "
                                  "and the AI Chat will use them to answer questions.")
        self.empty_label.setObjectName("MutedLabel")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        self.summary = QLabel("")
        self.summary.setObjectName("MutedLabel")
        layout.addWidget(self.summary)
        return card

    def _build_search_card(self):
        card, layout = make_card(
            "Try a search",
            "Type a question to see which passages the AI Chat would find. Managers see every document; "
            "employees only the ones marked “Everyone”.")
        row = QHBoxLayout()
        row.setSpacing(theme.SP_3)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("For example: how do I build a CNN?")
        self.search_input.returnPressed.connect(self._search)
        row.addWidget(self.search_input, 1)
        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("GhostButton")
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.clicked.connect(self._search)
        row.addWidget(self.search_button)
        layout.addLayout(row)

        self.results = QLabel("")
        self.results.setObjectName("MutedLabel")
        self.results.setWordWrap(True)
        self.results.setTextFormat(Qt.PlainText)
        self.results.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.results.setVisible(False)
        layout.addWidget(self.results)
        return card

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def refresh(self):
        """Reload the document list from the database."""
        docs = self.kb.documents(True) if self.kb else []
        key = tuple((d["id"], d["visibility"], d["updated_at"]) for d in docs)
        if key == self._last_key:
            return                      # nothing changed (the page is refreshed every 30 s)
        self._last_key = key
        self.table.setRowCount(len(docs))
        for row, doc in enumerate(docs):
            name_item = QTableWidgetItem(doc["filename"])
            name_item.setToolTip(doc["filename"])
            self.table.setItem(row, 0, name_item)

            combo = QComboBox()
            for value, label in VISIBILITY_LABELS:
                combo.addItem(label, value)
            combo.setStyleSheet("min-height: 0px; padding: 4px 10px;")
            combo.setFixedHeight(38)
            combo.setCurrentIndex(0 if doc["visibility"] == "everyone" else 1)
            combo.currentIndexChanged.connect(lambda _i, d=doc["id"], c=combo: self._set_visibility(d, c))
            holder = QWidget()                     # margins so the combo sits inside the row
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(8, 0, 8, 0)
            holder_layout.addWidget(combo)
            self.table.setCellWidget(row, 1, holder)
            holder.combo = combo

            self.table.setItem(row, 2, QTableWidgetItem("{:,}".format(doc["words"])))
            self.table.setItem(row, 3, QTableWidgetItem(_size_text(doc["size"])))
            self.table.setItem(row, 4, QTableWidgetItem(str(doc["updated_at"])[:16]))

            remove = QPushButton("Remove")
            remove.setObjectName("DangerButton")
            remove.setCursor(Qt.PointingHandCursor)
            remove.setStyleSheet("min-height: 0px; padding: 4px 14px;")
            remove.setFixedHeight(38)
            remove.clicked.connect(lambda _c=False, d=doc: self._remove(d))
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(8, 0, 8, 0)
            holder_layout.addWidget(remove)
            self.table.setCellWidget(row, 5, holder)
            holder.button = remove

        self.table.setVisible(bool(docs))
        self.empty_label.setVisible(not docs)
        if docs:
            self.table.setFixedHeight(self.table.horizontalHeader().height() + theme.TABLE_ROW_HEIGHT * len(docs) + 6)
            words = sum(d["words"] for d in docs)
            private = sum(1 for d in docs if d["visibility"] == "managers")
            self.summary.setText("%d document%s · %s words%s" % (
                len(docs), "" if len(docs) == 1 else "s", "{:,}".format(words),
                " · %d for managers only" % private if private else ""))
        else:
            self.summary.setText("")
        self.summary.setVisible(bool(docs))

    def _say(self, message, ok=True):
        self.status.setObjectName("SuccessLabel" if ok else "ErrorLabel")
        theme.repolish(self.status)
        self.status.setText(message)
        self.status.setVisible(True)

    # ------------------------------------------------------------------ #
    #  Adding / removing
    # ------------------------------------------------------------------ #
    def _choose_files(self):
        paths, _filter = QFileDialog.getOpenFileNames(self, "Add documents", "", FILE_FILTER)
        if paths:
            self.add_files(paths)

    def add_files(self, paths):
        """Add the given files (used by the button and by drag and drop)."""
        if self.kb is None:
            return
        visibility = self.visibility_combo.currentData()
        added, updated, problems = [], [], []
        for path in paths:
            try:
                _doc_id, created = self.kb.add_file(path, visibility, self.user.get("id"))
                (added if created else updated).append(os.path.basename(path))
            except KnowledgeError as error:
                problems.append(str(error))
        parts = []
        if added:
            parts.append("Added %d document%s." % (len(added), "" if len(added) == 1 else "s"))
        if updated:
            parts.append("Updated %s (same name)." % ", ".join(updated))
        if problems:
            parts.append("Not added: " + " ".join(problems))
        if parts:
            self._say(" ".join(parts), ok=bool(added or updated) and not problems)
        self.refresh()

    def _remove(self, doc):
        answer = QMessageBox.question(
            self, "Remove document",
            "Remove “%s”? The AI Chat will no longer use it." % doc["filename"],
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.kb.remove(doc["id"])
        self._say("Removed %s." % doc["filename"])
        self.refresh()

    def _set_visibility(self, doc_id, combo):
        self.kb.set_visibility(doc_id, combo.currentData())
        self._say("Changed who can read this document.")
        self.refresh()

    # ------------------------------------------------------------------ #
    #  Search test
    # ------------------------------------------------------------------ #
    def _search(self):
        question = self.search_input.text().strip()
        if not question or self.kb is None:
            return
        hits = self.kb.search(question, is_manager=True)
        self.results.setVisible(True)
        if not hits:
            self.results.setText("No passage matches this question — the AI Chat would answer without the documents.")
            return
        lines = []
        for number, hit in enumerate(hits, 1):
            where = hit.filename + (" — " + hit.heading if hit.heading else "")
            lines.append("%d. %s  (match %d%%)\n%s" % (number, where, round(hit.coverage * 100), hit.text))
        self.results.setText("\n\n".join(lines))

    # ------------------------------------------------------------------ #
    #  Drag and drop
    # ------------------------------------------------------------------ #
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.add_files(paths)
            event.acceptProposedAction()
