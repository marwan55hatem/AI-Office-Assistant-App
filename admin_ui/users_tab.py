"""Users tab: list, search, create, edit, toggle role and cascade-delete users."""

import logging

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from admin_ui.add_user_dialog import AddUserDialog, EditUserDialog
from ui import theme

logger = logging.getLogger(__name__)

HEADERS = ["ID", "USERNAME", "FULL NAME", "ROLE", "STATUS", "ACTIONS"]
ROW_HEIGHT = 56
ACTIONS_WIDTH = 360
BUTTON_HEIGHT = 38

STATUS_PILL = {
    "approved": "PillPresent",
    "pending": "PillDistracted",
    "rejected": "PillAbsent",
}


class UsersTab(QWidget):
    """Full CRUD over the ``users`` table."""

    changed = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._all_rows = []
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

        self.add_button = QPushButton("+  Add User")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self._on_add)

        self.refresh_button = QPushButton("🔄  Refresh")
        self.refresh_button.setObjectName("GhostButton")
        self.refresh_button.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔎  Search username or name...")
        self.search_input.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_filter)

        top.addWidget(self.add_button)
        top.addWidget(self.refresh_button)
        top.addStretch(1)
        top.addWidget(self.search_input, 1)
        layout.addLayout(top)

        self.count_label = QLabel("")
        self.count_label.setObjectName("MutedLabel")
        layout.addWidget(self.count_label)

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
        # The first five columns share the width; Actions gets a fixed slice wide
        # enough for the three labelled buttons.
        for column in range(len(HEADERS) - 1):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
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
    def refresh(self):
        """Reload the users table."""
        try:
            self._all_rows = self.db.get_all_users()
        except Exception as error:
            self._all_rows = []
            QMessageBox.critical(
                self, "Could not read the users",
                f"The database query failed:\n{error}",
            )
        self._populate(self._all_rows)

    def _apply_filter(self, _text=None):
        needle = self.search_input.text().strip().lower()
        if not needle:
            self._populate(self._all_rows)
            return
        rows = [
            row for row in self._all_rows
            if needle in str(row["username"]).lower()
            or needle in str(row["full_name"]).lower()
        ]
        self._populate(rows)

    def _populate(self, rows):
        self.table.setRowCount(0)
        self.table.clearSpans()

        if not rows:
            self.table.setRowCount(1)
            self.table.setRowHeight(0, ROW_HEIGHT)
            item = QTableWidgetItem("No users match.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, len(HEADERS))
            self.count_label.setText("0 users")
            return

        for row in rows:
            index = self.table.rowCount()
            self.table.insertRow(index)
            self.table.setRowHeight(index, ROW_HEIGHT)

            for column, value in enumerate(
                (str(row["id"]), row["username"], row["full_name"], row["role"])
            ):
                item = QTableWidgetItem(value)
                self.table.setItem(index, column, item)

            pill = QLabel(str(row.get("status", "approved")))
            pill.setObjectName(STATUS_PILL.get(row.get("status"), "PillMuted"))
            pill.setAlignment(Qt.AlignCenter)
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(theme.SP_2, 0, theme.SP_2, 0)
            holder_layout.addWidget(pill)
            self.table.setCellWidget(index, 4, holder)

            self.table.setCellWidget(index, 5, self._actions(row))

        self.count_label.setText(f"{len(rows)} users")

    def _actions(self, row):
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(theme.SP_1, 0, theme.SP_1, 0)
        layout.setSpacing(6)

        edit = self._action_button(
            "Edit", danger=False, tooltip="Edit this account"
        )
        edit.clicked.connect(lambda _checked=False, r=row: self._on_edit(r))

        toggle = self._action_button(
            "Switch role", danger=False,
            tooltip="Toggle role (switch between manager and employee)",
        )
        toggle.clicked.connect(lambda _checked=False, r=row: self._on_toggle_role(r))

        delete = self._action_button(
            "Delete", danger=True,
            tooltip="Delete this account and everything it owns",
        )
        delete.clicked.connect(lambda _checked=False, r=row: self._on_delete(r))

        for button in (edit, toggle, delete):
            layout.addWidget(button)
        layout.addStretch(1)
        return holder

    @staticmethod
    def _action_button(text, danger=False, tooltip=None):
        """Small labelled row-action button.

        The app-wide stylesheet pads buttons for full-width actions, which leaves
        no room for a label inside a table cell, so these carry their own compact
        (visually matching) style.  No emoji for destructive actions: the trash
        glyph (U+1F5D1) falls back to "WW" in Segoe UI on some machines.
        """
        button = QPushButton(text)
        button.setFixedHeight(BUTTON_HEIGHT)
        button.setCursor(Qt.PointingHandCursor)
        if tooltip:
            button.setToolTip(tooltip)

        button.setStyleSheet(theme.row_button_qss(danger=danger))

        # Pin the width to the styled size hint so no layout can squeeze it.
        button.setMinimumWidth(button.sizeHint().width() + 4)
        return button

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _on_add(self):
        dialog = AddUserDialog(self.db, parent=self)
        if dialog.exec_() == dialog.Accepted and dialog.created_id:
            self.refresh()
            self.changed.emit()

    def _on_edit(self, row):
        dialog = EditUserDialog(self.db, row, parent=self)
        if dialog.exec_() == dialog.Accepted:
            self.refresh()
            self.changed.emit()

    def _on_toggle_role(self, row):
        new_role = "employee" if row["role"] == "manager" else "manager"
        try:
            self.db.update_user(row["id"], role=new_role)
        except Exception as error:
            QMessageBox.critical(
                self, "Could not change the role",
                f"The database refused the update:\n{error}",
            )
            return
        self.refresh()
        self.changed.emit()

    def _related_counts(self, user_id):
        """Rows that would disappear with this user (zeros plus an error box if the query fails)."""
        try:
            return self.db.count_user_related_rows(user_id)
        except Exception as error:
            logger.warning("counting the rows of user %s failed", user_id, exc_info=True)
            QMessageBox.critical(
                self, "Could not count the dependent rows",
                f"The database query failed:\n{error}",
            )
            return {"sessions": 0, "events": 0, "tasks": 0, "calendar": 0, "chats": 0}

    def _on_delete(self, row):
        counts = self._related_counts(row["id"])
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Delete user")
        box.setText(
            f"Delete user '{row['username']}' ({row['full_name']})?\n\n"
            "This will also delete:\n"
            f"  • {counts['sessions']} sessions\n"
            f"  • {counts['events']} events\n"
            f"  • {counts['tasks']} tasks\n"
            f"  • {counts['calendar']} calendar events / invitations\n"
            f"  • {counts['chats']} assistant chats\n\n"
            "This action cannot be undone."
        )
        cancel = box.addButton("Cancel", QMessageBox.RejectRole)
        confirm = box.addButton("Delete Forever", QMessageBox.DestructiveRole)
        box.setDefaultButton(cancel)
        box.exec_()
        if box.clickedButton() is not confirm:
            return

        try:
            removed = self.db.delete_user_cascade(row["id"])
        except Exception as error:
            QMessageBox.critical(
                self, "Could not delete the user",
                f"The transaction was rolled back:\n{error}",
            )
            return

        self.refresh()
        self.changed.emit()
        QMessageBox.information(
            self, "User deleted",
            "Removed %(users)d user, %(sessions)d sessions, %(events)d events and "
            "%(tasks)d tasks." % removed,
        )
