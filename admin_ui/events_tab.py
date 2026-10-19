"""Events tab: filter the event log and delete individual events."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui import theme

HEADERS = ["ID", "SESSION ID", "USER", "EVENT", "TIMESTAMP", "ACTIONS"]
ROW_HEIGHT = 52

RANGES = [("Today", 1), ("Last 7 days", 7), ("All time", 3650)]
EVENT_TYPES = ["All", "focus", "distraction", "away"]

EVENT_COLOURS = {
    "focus": theme.SUCCESS,
    "distraction": theme.WARNING,
    "away": theme.DANGER,
}


class EventsTab(QWidget):
    """Read-mostly view of the ``events`` table."""

    changed = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_4)

        top = QHBoxLayout()
        top.setSpacing(theme.SP_3)

        self.range_combo = QComboBox()
        for label, days in RANGES:
            self.range_combo.addItem(label, days)
        self.range_combo.currentIndexChanged.connect(self.refresh)

        self.user_combo = QComboBox()
        self.user_combo.currentIndexChanged.connect(self.refresh)

        self.type_combo = QComboBox()
        self.type_combo.addItems(EVENT_TYPES)
        self.type_combo.currentIndexChanged.connect(self.refresh)

        self.refresh_button = QPushButton("🔄  Refresh")
        self.refresh_button.setObjectName("GhostButton")
        self.refresh_button.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)

        top.addWidget(QLabel("Range"))
        top.addWidget(self.range_combo)
        top.addWidget(QLabel("User"))
        top.addWidget(self.user_combo)
        top.addWidget(QLabel("Event"))
        top.addWidget(self.type_combo)
        top.addWidget(self.refresh_button)
        top.addStretch(1)
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
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        for column in range(len(HEADERS) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 130)
        layout.addWidget(self.table, 1)

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def refresh_users(self):
        """Reload the user filter, keeping the current choice."""
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
        """Reload the events table with the current filters."""
        if self.user_combo.count() == 0:
            self.refresh_users()
        days = self.range_combo.currentData()
        user_id = self.user_combo.currentData()
        event_type = self.type_combo.currentText()
        try:
            rows = self.db.get_all_events(
                user_id=user_id,
                event_type=None if event_type == "All" else event_type,
                days=days,
            )
        except Exception as error:
            rows = []
            QMessageBox.critical(
                self, "Could not read the events",
                f"The database query failed:\n{error}",
            )
        self._populate(rows)

    def _populate(self, rows):
        self.table.setRowCount(0)
        self.table.clearSpans()

        if not rows:
            self.table.setRowCount(1)
            self.table.setRowHeight(0, ROW_HEIGHT)
            item = QTableWidgetItem("No events match.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, len(HEADERS))
            self.summary_label.setText("0 events")
            return

        for row in rows:
            index = self.table.rowCount()
            self.table.insertRow(index)
            self.table.setRowHeight(index, ROW_HEIGHT)

            values = [
                (str(row["id"]), theme.TEXT_PRIMARY),
                (str(row["session_id"]), theme.TEXT_MUTED),
                (row["full_name"] or "—", theme.TEXT_PRIMARY),
            ]
            for column, (text, colour) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(colour))
                self.table.setItem(index, column, item)

            event_item = QTableWidgetItem(str(row["event_type"]))
            event_item.setForeground(
                QColor(EVENT_COLOURS.get(row["event_type"], theme.TEXT_MUTED))
            )
            self.table.setItem(index, 3, event_item)

            stamp = QTableWidgetItem(str(row["timestamp"] or ""))
            stamp.setForeground(QColor(theme.TEXT_MUTED))
            self.table.setItem(index, 4, stamp)

            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(theme.SP_1, 0, theme.SP_1, 0)
            delete = QPushButton("Delete")
            delete.setStyleSheet(theme.row_button_qss(danger=True))
            delete.setFixedSize(92, 38)
            delete.setCursor(Qt.PointingHandCursor)
            delete.setToolTip(f"Delete event {row['id']}")
            delete.clicked.connect(
                lambda _checked=False, r=row: self._on_delete(r)
            )
            holder_layout.addWidget(delete)
            self.table.setCellWidget(index, 5, holder)

        self.summary_label.setText(f"{len(rows)} events")

    def _on_delete(self, row):
        answer = QMessageBox.question(
            self, "Delete event",
            f"Delete event {row['id']} ({row['event_type']} at {row['timestamp']})?",
            QMessageBox.Cancel | QMessageBox.Yes,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.db.delete_event(row["id"])
        except Exception as error:
            QMessageBox.critical(
                self, "Could not delete the event",
                f"The database refused the delete:\n{error}",
            )
            return
        self.refresh()
        self.changed.emit()
