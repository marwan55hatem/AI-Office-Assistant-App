"""AI Helper screen: document summarization (BART) and a text translator."""

import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from assistant.ai_worker import AIWorker
from assistant.extractors import extract_text
from assistant.summarizer import Summarizer
from assistant.translator import Translator
from ui import theme

MAX_CHARS = 5000


class DropZone(QFrame):
    """Clickable frame that emulates a drag & drop file target."""

    def __init__(self, on_click, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self.setObjectName("DropZone")
        self.setMinimumHeight(300)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to choose a PDF or TXT file")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


class AIHelperScreen(QWidget):
    """Two-tab helper screen (summarize / translate), fully demo driven."""

    go_back = pyqtSignal()

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": 2, "full_name": "Marwan Hatem"}
        self.db = db
        self.file_path = ""

        # Summarization state: the Summarizer is cached so the BART model stays
        # warm between runs, and the worker is kept so the QThread is not
        # garbage-collected mid-flight.
        self._summarizer = None     # lazy
        self._sum_worker = None
        self._sum_busy = False

        # Translation state (same pattern: cached model + one worker at a time).
        self._translator = None
        self._trans_worker = None
        self._trans_busy = False

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # The shell's sidebar handles navigation, so this page has no navbar of
        # its own - just an in-page title above the tabs.
        root.addWidget(self._build_header())

        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        root.addWidget(divider)

        tabs_wrapper = QVBoxLayout()
        tabs_wrapper.setContentsMargins(theme.SP_6, theme.SP_5, theme.SP_6, theme.SP_6)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_summarize_tab(), "📝   Summarize")
        self.tabs.addTab(self._build_translate_tab(), "🌐   Translate")

        tabs_wrapper.addWidget(self.tabs)
        root.addLayout(tabs_wrapper, 1)

    def refresh(self):
        """Pages expose refresh() for the shell's navigation/timer hook."""

    def _build_header(self):
        header = QFrame()
        header.setObjectName("Navbar")
        header.setFixedHeight(theme.NAVBAR_HEIGHT)

        row = QHBoxLayout(header)
        row.setContentsMargins(theme.SP_6, 0, theme.SP_6, 0)
        row.setSpacing(theme.SP_3)

        title = QLabel("🤖  AI Helper")
        title.setObjectName("H3")
        row.addWidget(title)
        row.addStretch(1)

        return header

    # ------------------------------ tab 1 ------------------------------ #
    def _build_summarize_tab(self):
        page = QWidget()
        page.setObjectName("TabPage")

        columns = QHBoxLayout(page)
        columns.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        columns.setSpacing(theme.SP_6)
        columns.addWidget(self._build_summarize_left(), 0)
        columns.addWidget(self._build_summarize_right(), 1)

        return page

    def _build_summarize_left(self):
        column = QWidget()
        column.setFixedWidth(380)

        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_3)

        drop_zone = DropZone(self._pick_file)
        drop_zone.setMinimumHeight(220)
        drop_layout = QVBoxLayout(drop_zone)
        drop_layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        drop_layout.setSpacing(theme.SP_2)
        drop_layout.addStretch(1)

        icon = QLabel("📄")
        icon.setObjectName("Logo")
        icon.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(icon)

        hint = QLabel("Drop PDF or TXT file here\nor click to browse")
        hint.setObjectName("BodyLabel")
        hint.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(hint)
        drop_layout.addStretch(1)

        layout.addWidget(drop_zone, 3)

        self.file_label = QLabel("No file selected")
        self.file_label.setObjectName("BodyLabel")
        self.file_label.setAlignment(Qt.AlignCenter)
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        self.summarize_button = QPushButton("✨   Summarize")
        self.summarize_button.setObjectName("PrimaryButton")
        self.summarize_button.setMinimumHeight(54)
        self.summarize_button.setCursor(Qt.PointingHandCursor)
        self.summarize_button.clicked.connect(self._on_summarize)
        layout.addWidget(self.summarize_button)

        self.sum_status = QLabel("")
        self.sum_status.setObjectName("MutedLabel")
        self.sum_status.setAlignment(Qt.AlignCenter)
        self.sum_status.setWordWrap(True)
        layout.addWidget(self.sum_status)

        tip = QFrame()
        tip.setObjectName("Card")
        tip_layout = QVBoxLayout(tip)
        tip_layout.setContentsMargins(theme.SP_4, theme.SP_3, theme.SP_4, theme.SP_3)
        tip_label = QLabel("💡  Tip: PDF and TXT up to ~50 pages work best.")
        tip_label.setObjectName("MutedLabel")
        tip_label.setWordWrap(True)
        tip_layout.addWidget(tip_label)
        layout.addWidget(tip)

        layout.addStretch(1)
        return column

    def _build_summarize_right(self):
        column = QWidget()

        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_2)

        header = QLabel("Summary Result")
        header.setObjectName("SectionHeader")
        layout.addWidget(header)

        self.summary_output = QTextEdit()
        self.summary_output.setReadOnly(True)
        self.summary_output.setMinimumHeight(280)
        self.summary_output.setPlaceholderText("Your summary will appear here...")
        layout.addWidget(self.summary_output, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP_2)

        copy_button = QPushButton("📋  Copy")
        copy_button.setObjectName("GhostButton")
        copy_button.setCursor(Qt.PointingHandCursor)
        copy_button.clicked.connect(lambda: self._copy_text(self.summary_output))

        save_button = QPushButton("💾  Save as TXT")
        save_button.setObjectName("GhostButton")
        save_button.setCursor(Qt.PointingHandCursor)
        save_button.clicked.connect(
            lambda: self._save_text(self.summary_output, "summary.txt")
        )

        buttons.addWidget(copy_button)
        buttons.addWidget(save_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        return column

    # ------------------------------ tab 2 ------------------------------ #
    def _build_translate_tab(self):
        page = QWidget()
        page.setObjectName("TabPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        layout.setSpacing(theme.SP_4)

        layout.addLayout(self._build_language_row())

        columns = QHBoxLayout()
        columns.setSpacing(theme.SP_6)
        columns.addWidget(self._build_translate_left(), 1)
        columns.addWidget(self._build_translate_right(), 1)
        layout.addLayout(columns, 1)

        return page

    def _build_language_row(self):
        row = QHBoxLayout()
        row.setSpacing(theme.SP_3)

        languages = ["English", "Arabic", "French", "German"]

        self.src_lang = QComboBox()
        self.src_lang.addItems(languages)
        self.src_lang.setMinimumWidth(220)

        arrow = QLabel("➜")
        arrow.setObjectName("H2")
        arrow.setStyleSheet("color: %s; background: transparent;" % theme.ACCENT)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setMinimumWidth(40)

        self.tgt_lang = QComboBox()
        self.tgt_lang.addItems(["Arabic", "English", "French", "German"])
        self.tgt_lang.setMinimumWidth(220)

        swap = QPushButton("⇄  Swap")
        swap.setObjectName("GhostButton")
        swap.setCursor(Qt.PointingHandCursor)
        swap.setToolTip("Swap the source and target languages")
        swap.clicked.connect(self._swap_languages)

        row.addWidget(self.src_lang)
        row.addWidget(arrow)
        row.addWidget(self.tgt_lang)
        row.addWidget(swap)
        row.addStretch(1)
        return row

    def _swap_languages(self):
        """Swap the two language combos and clear the previous result."""
        source = self.src_lang.currentText()
        target = self.tgt_lang.currentText()
        self.src_lang.setCurrentText(target)
        self.tgt_lang.setCurrentText(source)
        self.translate_output.clear()
        self.trans_status_label.clear()

    def _build_translate_left(self):
        column = QWidget()

        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_2)

        header = QLabel("Source Text")
        header.setObjectName("SectionHeader")
        layout.addWidget(header)

        self.translate_input = QTextEdit()
        self.translate_input.setPlaceholderText("Type or paste text here...")
        self.translate_input.setMinimumHeight(280)
        self.translate_input.textChanged.connect(self._update_char_count)
        layout.addWidget(self.translate_input, 1)

        self.char_count = QLabel("0 / 5000")
        self.char_count.setObjectName("CharCount")
        self.char_count.setAlignment(Qt.AlignRight)
        layout.addWidget(self.char_count)

        self.translate_button = QPushButton("🌐   Translate")
        self.translate_button.setObjectName("PrimaryButton")
        self.translate_button.setMinimumHeight(54)
        self.translate_button.setCursor(Qt.PointingHandCursor)
        self.translate_button.clicked.connect(self._on_translate)
        layout.addWidget(self.translate_button)

        self.trans_status_label = QLabel("")
        self.trans_status_label.setObjectName("MutedLabel")
        self.trans_status_label.setAlignment(Qt.AlignCenter)
        self.trans_status_label.setWordWrap(True)
        layout.addWidget(self.trans_status_label)

        return column

    def _build_translate_right(self):
        column = QWidget()

        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SP_2)

        header = QLabel("Translation Result")
        header.setObjectName("SectionHeader")
        layout.addWidget(header)

        self.translate_output = QTextEdit()
        self.translate_output.setReadOnly(True)
        self.translate_output.setPlaceholderText("Translation will appear here...")
        layout.addWidget(self.translate_output, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP_2)

        copy_button = QPushButton("📋  Copy")
        copy_button.setObjectName("GhostButton")
        copy_button.setCursor(Qt.PointingHandCursor)
        copy_button.clicked.connect(lambda: self._copy_text(self.translate_output))

        save_button = QPushButton("💾  Save as TXT")
        save_button.setObjectName("GhostButton")
        save_button.setCursor(Qt.PointingHandCursor)
        save_button.clicked.connect(
            lambda: self._save_text(self.translate_output, "translation.txt")
        )

        buttons.addWidget(copy_button)
        buttons.addWidget(save_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        return column

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a document", "", "Documents (*.pdf *.txt)"
        )
        if not path:
            return
        self.file_path = path
        self.file_label.setText(f"📎  {os.path.basename(path)}")

    def _on_summarize(self):
        if not self.file_path:
            QMessageBox.warning(
                self,
                "No file selected",
                "Please choose a PDF or TXT file first.",
            )
            return

        if self._sum_busy:
            return  # a run is already in flight

        self._sum_busy = True
        self.summarize_button.setEnabled(False)
        self.sum_status.setText("⏳  Extracting text…")
        self.summary_output.clear()
        # Let the status text paint before the (short) extraction runs.
        QApplication.processEvents()

        try:
            text = extract_text(self.file_path)
        except Exception as error:
            self._sum_busy = False
            self.summarize_button.setEnabled(True)
            self.sum_status.setText("")
            QMessageBox.critical(self, "Could not read file", str(error))
            return

        if not text.strip():
            self._sum_busy = False
            self.summarize_button.setEnabled(True)
            self.sum_status.setText("")
            QMessageBox.warning(
                self, "Empty file", "No text could be extracted."
            )
            return

        if self._summarizer is None:
            self._summarizer = Summarizer()

        if Summarizer.is_loaded():
            self.sum_status.setText(
                f"⏳  Summarizing {len(text):,} characters…"
            )
        else:
            self.sum_status.setText(
                "⏳  Loading summarization model (first run only, ~1.6 GB)…"
            )
        QApplication.processEvents()

        # The worker imports torch/transformers and loads the model itself, so
        # the GUI thread never blocks on the heavy setup.
        self._sum_worker = AIWorker(self._summarizer.summarize, text)
        self._sum_worker.finished_ok.connect(self._on_summary_done)
        self._sum_worker.failed.connect(self._on_summary_failed)
        self._sum_worker.finished.connect(self._on_summary_finished)
        self._sum_worker.start()

    def _on_summary_done(self, summary_text):
        self.summary_output.setPlainText(summary_text)
        self.sum_status.setText("✅  Done")

    def _on_summary_failed(self, error_message):
        QMessageBox.critical(self, "Summarization failed", error_message)
        self.sum_status.setText("")

    def _on_summary_finished(self):
        self._sum_busy = False
        self.summarize_button.setEnabled(True)

    def _on_translate(self):
        text = self.translate_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(
                self, "Empty input", "Please type some text to translate."
            )
            return
        if len(text) > MAX_CHARS:
            QMessageBox.warning(
                self,
                "Too long",
                f"Maximum {MAX_CHARS:,} characters. Please shorten the text.",
            )
            return

        src = self.src_lang.currentText()
        tgt = self.tgt_lang.currentText()
        if src == tgt:
            QMessageBox.warning(
                self, "Same language", "Source and target must differ."
            )
            return
        if self._trans_busy:
            return  # a run is already in flight

        self._trans_busy = True
        self.translate_button.setEnabled(False)
        self.translate_output.clear()

        try:
            self._translator = Translator(src, tgt)
        except Exception as error:
            self._trans_busy = False
            self.translate_button.setEnabled(True)
            self.trans_status_label.setText("")
            QMessageBox.critical(self, "Translation failed", str(error))
            return

        # The pair may already be cached in Translator._cache from an earlier run
        # (switching en->ar -> en->fr -> en->ar must not claim a fresh download),
        # so the status reflects the model cache rather than the last-used pair.
        pair_ready = all(
            (leg_src, leg_tgt) in Translator._cache
            for leg_src, leg_tgt, _model in self._translator._legs
        )
        if pair_ready:
            self.trans_status_label.setText("⏳  Translating…")
        elif self._translator.uses_pivot:
            # No direct model for this pair: it is translated through English.
            self.trans_status_label.setText(
                f"⏳  Loading {src}→{tgt} models (via English, "
                f"~300 MB download on first use)…"
            )
        else:
            self.trans_status_label.setText(
                f"⏳  Loading {src}→{tgt} model (~300 MB download on first use)…"
            )
        QApplication.processEvents()

        self._trans_worker = AIWorker(self._translator.translate, text)
        self._trans_worker.finished_ok.connect(self._on_translate_done)
        self._trans_worker.failed.connect(self._on_translate_failed)
        self._trans_worker.finished.connect(self._on_translate_finished)
        self._trans_worker.start()

    def _on_translate_done(self, translated):
        self.translate_output.setPlainText(translated)
        if self.tgt_lang.currentText() == "Arabic":
            self.translate_output.setLayoutDirection(Qt.RightToLeft)
        else:
            self.translate_output.setLayoutDirection(Qt.LeftToRight)
        self.trans_status_label.setText("✅  Done")

    def _on_translate_failed(self, error_message):
        QMessageBox.critical(self, "Translation failed", error_message)
        self.trans_status_label.setText("")

    def _on_translate_finished(self):
        self._trans_busy = False
        self.translate_button.setEnabled(True)

    def _update_char_count(self):
        count = len(self.translate_input.toPlainText())
        self.char_count.setText(f"{count} / {MAX_CHARS}")
        over = count > MAX_CHARS
        self.char_count.setProperty("over", "true" if over else "false")
        theme.repolish(self.char_count)

    def _copy_text(self, text_edit):
        text = text_edit.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Nothing to copy", "There is no text to copy yet.")
            return
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "Text copied to the clipboard.")

    def _save_text(self, text_edit, default_name):
        text = text_edit.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Nothing to save", "There is no text to save yet.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save as TXT", default_name, "Text files (*.txt)"
        )
        if not path:
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"

        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as error:
            QMessageBox.critical(self, "Could not save", str(error))
            return

        QMessageBox.information(self, "Saved", f"Saved to:\n{path}")
