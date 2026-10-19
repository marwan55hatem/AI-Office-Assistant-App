"""Tasks tab: filter, create and delete tasks, and clear the completed ones."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
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

from ui import theme

HEADERS = ["ID", "USER", "ASSIGNED BY", "TITLE", "PRIORITY", "DONE", "CREATED",
           "ACTIONS"]
ROW_HEIGHT = 52
NEW_TASK_TITLE = "+  Add Task"


class NewTaskDialog(QDialog):
    """Pick an owner, a title and a priority for a new task."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle(NEW_TASK_TITLE)
        self.setMinimumWidth(540)
        self.db = db
        self.created_id = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        layout.setSpacing(theme.SP_3)

        heading = QLabel(NEW_TASK_TITLE)
        heading.setObjectName("H2")
        layout.addWidget(heading)

        self.user_combo = QComboBox()
        try:
            for employee in db.get_all_employees():
                self.user_combo.addItem(employee["full_name"], employee["id"])
        except Exception as error:
            QMessageBox.critical(self, "Could not list the users", str(error))
        layout.addWidget(self.user_combo)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Task title...")
        self.title_input.setMinimumHeight(theme.FIELD_HEIGHT)
        layout.addWidget(self.title_input)

        row = QHBoxLayout()
        row.setSpacing(theme.SP_2)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.priority_buttons = {}
        for value, label in (("normal", "Normal"), ("urgent", "Urgent")):
            button = QPushButton(label)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(48)
            button.setCursor(Qt.PointingHandCursor)
            group.addButton(button)
            row.addWidget(button, 1)
            self.priority_buttons[value] = button
        self.priority_buttons["normal"].setChecked(True)
        layout.addLayout(row)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP_3)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("GhostButton")
        cancel.setMinimumHeight(54)
        cancel.clicked.connect(self.reject)
        create = QPushButton("Add Task")
        create.setObjectName("PrimaryButton")
        create.setMinimumHeight(54)
        create.setCursor(Qt.PointingHandCursor)
        create.clicked.connect(self._on_submit)
        buttons.addWidget(cancel, 1)
        buttons.addWidget(create, 1)
        layout.addLayout(buttons)

    def _priority(self):
        return "urgent" if self.priority_buttons["urgent"].isChecked() else "normal"

    def _on_submit(self):
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "Missing title", "Please type a task title.")
            return
        user_id = self.user_combo.currentData()
        if user_id is None:
            QMessageBox.warning(self, "No user", "There is no employee to assign it to.")
            return
        try:
            self.created_id = self.db.add_task(
                user_id, title, priority=self._priority(),
                # assigned_by=1 is the seeded manager 'Admin Manager'.
                # The admin panel does not have its own user row, so we use the
                # manager's id as the assigner. Intentional.
                assigned_by=1
            )
        except Exception as error:
            QMessageBox.critical(self, "Could not add the task", str(error))
            return
        self.accept()


class TasksTab(QWidget):
    """Every task in the database."""

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

        self.user_combo = QComboBox()
        self.user_combo.currentIndexChanged.connect(self.refresh)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["All", "normal", "urgent"])
        self.priority_combo.currentIndexChanged.connect(self.refresh)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "open", "done"])
        self.status_combo.currentIndexChanged.connect(self.refresh)

        self.refresh_button = QPushButton("🔄  Refresh")
        self.refresh_button.setObjectName("GhostButton")
        self.refresh_button.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)

        self.add_button = QPushButton(NEW_TASK_TITLE)
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self._on_add)

        self.clear_button = QPushButton("Clear completed")
        self.clear_button.setObjectName("DangerButton")
        self.clear_button.setMinimumHeight(theme.BUTTON_HEIGHT)
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self._on_clear_completed)

        top.addWidget(QLabel("User"))
        top.addWidget(self.user_combo)
        top.addWidget(QLabel("Priority"))
        top.addWidget(self.priority_combo)
        top.addWidget(QLabel("Status"))
        top.addWidget(self.status_combo)
        top.addWidget(self.refresh_button)
        top.addStretch(1)
        top.addWidget(self.add_button)
        top.addWidget(self.clear_button)
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
        for column in range(len(HEADERS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        # Cell widgets (the pills and buttons) are not measured by
        # ResizeToContents, so those columns get explicit widths.
        for column, width in ((4, 140), (5, 130), (7, 130)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)
        layout.addWidget(self.table, 1)

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def refresh_users(self):
        """Reload the user filter, keeping the current choice."""
        current = self.user_combo.currentData()
        try:
            employees = self.db.get_all_employees()
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
        """Reload the tasks table with the current filters."""
        if self.user_combo.count() == 0:
            self.refresh_users()

        priority = self.priority_combo.currentText()
        status = self.status_combo.currentText()
        try:
            rows = self.db.get_all_tasks(
                user_id=self.user_combo.currentData(),
                priority=None if priority == "All" else priority,
                done=None if status == "All" else (status == "done"),
            )
        except Exception as error:
            rows = []
            QMessageBox.critical(
                self, "Could not read the tasks",
                f"The database query failed:\n{error}",
            )
        self._populate(rows)

    def _populate(self, rows):
        self.table.setRowCount(0)
        self.table.clearSpans()

        if not rows:
            self.table.setRowCount(1)
            self.table.setRowHeight(0, ROW_HEIGHT)
            item = QTableWidgetItem("No tasks match.")
            item.setForeground(QColor(theme.TEXT_MUTED))
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, len(HEADERS))
            self.summary_label.setText("0 tasks")
            return

        for row in rows:
            index = self.table.rowCount()
            self.table.insertRow(index)
            self.table.setRowHeight(index, ROW_HEIGHT)

            for column, value in enumerate(
                (
                    str(row["id"]),
                    row["full_name"] or "—",
                    row["assigned_by_name"] or "—",
                )
            ):
                item = QTableWidgetItem(value)
                item.setForeground(QColor(theme.TEXT_PRIMARY))
                self.table.setItem(index, column, item)

            title_item = QTableWidgetItem(str(row["title"]))
            title_item.setForeground(
                QColor(theme.TEXT_MUTED if row["is_done"] else theme.TEXT_PRIMARY)
            )
            self.table.setItem(index, 3, title_item)

            urgent = str(row["priority"]) == "urgent"
            priority_pill = QLabel("URGENT" if urgent else "Normal")
            priority_pill.setObjectName("PillUrgent" if urgent else "PillMuted")
            priority_pill.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(index, 4, self._cell(priority_pill))

            done = bool(row["is_done"])
            done_pill = QLabel("✓ Done" if done else "Open")
            done_pill.setObjectName("PillDone" if done else "PillMuted")
            done_pill.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(index, 5, self._cell(done_pill))

            created = QTableWidgetItem(str(row.get("created_at") or "—"))
            created.setForeground(QColor(theme.TEXT_MUTED))
            self.table.setItem(index, 6, created)

            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(theme.SP_1, 0, theme.SP_1, 0)
            delete = QPushButton("Delete")
            delete.setStyleSheet(theme.row_button_qss(danger=True))
            delete.setFixedSize(92, 38)
            delete.setCursor(Qt.PointingHandCursor)
            delete.setToolTip(f"Delete task {row['id']}")
            delete.clicked.connect(lambda _checked=False, r=row: self._on_delete(r))
            holder_layout.addWidget(delete)
            self.table.setCellWidget(index, 7, holder)

        open_count = sum(1 for row in rows if not row["is_done"])
        self.summary_label.setText(
            f"{len(rows)} tasks  ·  {open_count} open  ·  {len(rows) - open_count} done"
        )

    @staticmethod
    def _cell(widget):
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(theme.SP_2, 0, theme.SP_2, 0)
        layout.addWidget(widget)
        return holder

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _on_add(self):
        dialog = NewTaskDialog(self.db, parent=self)
        if dialog.exec_() == dialog.Accepted and dialog.created_id:
            self.refresh()
            self.changed.emit()

    def _on_delete(self, row):
        answer = QMessageBox.question(
            self, "Delete task", f"Delete task {row['id']} ({row['title']})?",
            QMessageBox.Cancel | QMessageBox.Yes, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.db.delete_task(row["id"])
        except Exception as error:
            QMessageBox.critical(
                self, "Could not delete the task",
                f"The database refused the delete:\n{error}",
            )
            return
        self.refresh()
        self.changed.emit()

    def _on_clear_completed(self):
        try:
            pending = len(self.db.get_all_tasks(done=True))
        except Exception as error:
            QMessageBox.critical(self, "Could not count the tasks", str(error))
            return
        if not pending:
            QMessageBox.information(self, "Nothing to clear",
                                    "There are no completed tasks.")
            return
        answer = QMessageBox.question(
            self, "Clear completed tasks",
            f"Delete all {pending} completed task(s)? This cannot be undone.",
            QMessageBox.Cancel | QMessageBox.Yes, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            removed = self.db.clear_completed_tasks()
        except Exception as error:
            QMessageBox.critical(
                self, "Could not clear the tasks",
                f"The database refused the delete:\n{error}",
            )
            return
        self.refresh()
        self.changed.emit()
        QMessageBox.information(self, "Tasks cleared",
                                f"Removed {removed} completed task(s).")
