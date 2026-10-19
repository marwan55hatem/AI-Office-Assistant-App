"""Sessions tab: browse, filter and bulk-delete sessions (with their events)."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui import theme

HEADERS = ["ID", "DATE", "USER", "START", "END", "FOCUS", "DISTRACTED", "AWAY",
           "DISTR (SCREEN)", "PRODUCTIVE", "IDLE", "ACTIONS"]
ROW_HEIGHT = 56
ACTIONS_WIDTH = 130
BUTTON_HEIGHT = 38
DELETE_PHRASE = "DELETE ALL SESSIONS"

RANGES = [("Today", 1), ("Last 7 days", 7), ("Last 30 days", 30), ("All time", 3650)]

_fmt_hms = theme.fmt_hms


def _delete_action_button(tooltip):
    """Small labelled destructive row action.

    Plain text on purpose: the trash glyph (U+1F5D1) falls back to "WW" in
    Segoe UI on some machines, so the label carries the meaning instead.
    """
    button = QPushButton("Delete")
    button.setFixedHeight(BUTTON_HEIGHT)
    button.setCursor(Qt.PointingHandCursor)
    button.setToolTip(tooltip)
    button.setStyleSheet(theme.row_button_qss(danger=True))
    button.setMinimumWidth(button.sizeHint().width() + 4)
    return button


class SessionsTab(QWidget):
    """Every session row, with per-row and bulk deletion."""

    changed = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._rows = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_4)

        top = QHBoxLayout()
        top.setSpacing(theme.SP_3)

        self.range_combo = QComboBox()
        for label, days in RANGES:
            self.range_combo.addItem(label, days)
        self.range_combo.setCurrentIndex(3)          # All time
        self.range_combo.currentIndexChanged.connect(self.refresh)

        self.user_combo = QComboBox()
        self.user_combo.currentIndexChanged.connect(self.refresh)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔎  Filter by username...")
        self.search_input.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_search)

        self.refresh_button = QPushButton("🔄  Refresh")
        self.refresh_button.setObjectName("GhostButton")
        self.refresh_button.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)

        self.delete_selected_button = QPushButton("Delete selected")
        self.delete_selected_button.setObjectName("DangerButton")
        self.delete_selected_button.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.delete_selected_button.setCursor(Qt.PointingHandCursor)
        self.delete_selected_button.setEnabled(False)
        self.delete_selected_button.clicked.connect(self._on_delete_selected)

        self.delete_all_button = QPushButton("Delete ALL filtered")
        self.delete_all_button.setObjectName("DangerButton")
        self.delete_all_button.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.delete_all_button.setCursor(Qt.PointingHandCursor)
        self.delete_all_button.setToolTip("Requires typing a confirmation phrase")
        self.delete_all_button.clicked.connect(self._on_delete_all)

        top.addWidget(QLabel("Range"))
        top.addWidget(self.range_combo)
        top.addWidget(QLabel("User"))
        top.addWidget(self.user_combo)
        top.addWidget(self.search_input, 1)
        top.addWidget(self.refresh_button)
        top.addStretch(1)
        top.addWidget(self.delete_selected_button)
        top.addWidget(self.delete_all_button)
        layout.addLayout(top)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("MutedLabel")
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setFixedHeight(theme.TABLE_HEADER_HEIGHT)
        self.table.verticalHeader().setDefaultSectionSize(theme.TABLE_ROW_HEIGHT)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        for column in range(len(HEADERS) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(len(HEADERS) - 1, QHeaderView.Fixed)
        self.table.setColumnWidth(len(HEADERS) - 1, ACTIONS_WIDTH)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)

        actions_header = QTableWidgetItem("ACTIONS")
        actions_header.setTextAlignment(Qt.AlignCenter)
        self.table.setHorizontalHeaderItem(len(HEADERS) - 1, actions_header)
        layout.addWidget(self.table, 1)

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def refresh_users(self):
        """Keep the user filter in step with the users table."""
        current = self.user_combo.currentData()
        try:
            employees = self.db.get_all_users()
        except Exception:
            employees = []
        self.user_combo.blockSignals(True)
        self.user_combo.clear()
        self.user_combo.addItem("All users", None)
        for employee in employees:
            self.user_combo.addItem(employee["full_name"], employee["id"])
        index = self.user_combo.findData(current)
        self.user_combo.setCurrentIndex(index if index >= 0 else 0)
        self.user_combo.blockSignals(False)

    def refresh(self):
        """Reload the sessions table with the current filters."""
        if self.user_combo.count() == 0:
            self.refresh_users()
        days = self.range_combo.currentData()
        user_id = self.user_combo.currentData()
        try:
            self._rows = self.db.get_sessions_history(
                user_id=user_id, days=days
            )
            if user_id is not None:
                self._rows = [row for row in self._rows
                              if row["user_id"] == user_id]
        except Exception as error:
            self._rows = []
            QMessageBox.critical(
                self, "Could not read the sessions",
                f"The database query failed:\n{error}",
            )
        self._apply_search()

    def _visible_rows(self):
        needle = self.search_input.text().strip().lower()
        if not needle:
            return self._rows
        return [row for row in self._rows
                if needle in str(row["full_name"]).lower()]

    def _apply_search(self, _text=None):
        rows = self._visible_rows()
        self.table.setRowCount(0)
        self.table.clearSpans()

        if not rows:
            self.table.setRowCount(1)
            self.table.setRowHeight(0, ROW_HEIGHT)
            item = QTableWidgetItem("No sessions match.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, len(HEADERS))
            self.summary_label.setText("0 sessions")
            self._on_selection_changed()
            return

        for row in rows:
            index = self.table.rowCount()
            self.table.insertRow(index)
            self.table.setRowHeight(index, ROW_HEIGHT)

            values = [
                (str(row["id"]), theme.TEXT_PRIMARY),
                (row["date"], theme.TEXT_PRIMARY),
                (row["full_name"], theme.TEXT_PRIMARY),
                (row["start_time"] or "—", theme.TEXT_MUTED),
                (row["end_time"] or "active",
                 theme.WARNING if row["end_time"] is None else theme.TEXT_MUTED),
                (_fmt_hms(row["focus_seconds"]), theme.SUCCESS),
                (_fmt_hms(row["distraction_seconds"]), theme.WARNING),
                (_fmt_hms(row["away_seconds"]), theme.DANGER),
                (_fmt_hms(row.get("screen_distracted_seconds")), theme.TEXT_MUTED),
                (_fmt_hms(row.get("screen_productive_seconds")), theme.TEXT_MUTED),
                (_fmt_hms(row.get("screen_idle_seconds")), theme.TEXT_MUTED),
            ]
            for column, (text, colour) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(colour))
                self.table.setItem(index, column, item)

            self.table.setCellWidget(
                index, len(HEADERS) - 1, self._delete_button(row)
            )

        total_focus = sum(row["focus_seconds"] for row in rows)
        total_distraction = sum(row["distraction_seconds"] for row in rows)
        total_away = sum(row["away_seconds"] for row in rows)
        self.summary_label.setText(
            f"{len(rows)} sessions  ·  focus {_fmt_hms(total_focus)}  ·  "
            f"distracted {_fmt_hms(total_distraction)}  ·  away {_fmt_hms(total_away)}"
        )
        self._on_selection_changed()

    def _delete_button(self, row):
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(theme.SP_1, 0, theme.SP_1, 0)

        button = _delete_action_button(f"Delete session {row['id']} and its events")
        button.clicked.connect(lambda _checked=False, r=row: self._on_delete_one(r))
        layout.addWidget(button)
        layout.addStretch(1)
        return holder

    # ------------------------------------------------------------------ #
    #  Selection / deletion
    # ------------------------------------------------------------------ #
    def selected_ids(self):
        """Database ids of the selected session rows."""
        ids = []
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item is not None and item.text().isdigit():
                ids.append(int(item.text()))
        return ids

    def _on_selection_changed(self):
        count = len(self.selected_ids())
        self.delete_selected_button.setEnabled(count > 0)
        self.delete_selected_button.setText(
            f"Delete selected ({count})" if count else "Delete selected"
        )

    def _on_delete_one(self, row):
        answer = QMessageBox.question(
            self, "Delete session",
            f"Delete session {row['id']} ({row['full_name']}, {row['date']}) and "
            f"all of its events?",
            QMessageBox.Cancel | QMessageBox.Yes,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            removed = self.db.delete_session(row["id"])
        except Exception as error:
            QMessageBox.critical(
                self, "Could not delete the session",
                f"The transaction was rolled back:\n{error}",
            )
            return
        self.refresh()
        self.changed.emit()
        QMessageBox.information(
            self, "Session deleted",
            "Removed %d session(s) and %d event(s)."
            % (removed["sessions"], removed["events"]),
        )

    def _on_delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        answer = QMessageBox.question(
            self, "Delete sessions",
            f"Delete {len(ids)} sessions and all their events?",
            QMessageBox.Cancel | QMessageBox.Yes,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            removed = self.db.delete_sessions_by_ids(ids)
        except Exception as error:
            QMessageBox.critical(
                self, "Could not delete the sessions",
                f"The transaction was rolled back:\n{error}",
            )
            return
        self.refresh()
        self.changed.emit()
        QMessageBox.information(
            self, "Sessions deleted",
            "Removed %d session(s) and %d event(s)."
            % (removed["sessions"], removed["events"]),
        )

    def _on_delete_all(self):
        rows = self._visible_rows()
        if not rows:
            QMessageBox.information(self, "Nothing to delete",
                                    "No sessions match the current filters.")
            return

        phrase, accepted = QInputDialog.getText(
            self, "Delete ALL filtered sessions",
            f"This deletes {len(rows)} session(s) matching the current filters,\n"
            f"including every event they contain.\n\n"
            f"Type {DELETE_PHRASE!r} to confirm:",
        )
        if not accepted or phrase.strip() != DELETE_PHRASE:
            QMessageBox.information(self, "Aborted", "The phrase did not match.")
            return

        try:
            removed = self.db.delete_sessions_by_ids([row["id"] for row in rows])
        except Exception as error:
            QMessageBox.critical(
                self, "Could not delete the sessions",
                f"The transaction was rolled back:\n{error}",
            )
            return
        self.refresh()
        self.changed.emit()
        QMessageBox.information(
            self, "Sessions deleted",
            "Removed %d session(s) and %d event(s)."
            % (removed["sessions"], removed["events"]),
        )
