"""To-do list screen: manager-assigned tasks plus the employee's own tasks."""

import logging
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from assistant.formatting import deadline_state, format_deadline

logger = logging.getLogger(__name__)


class TodoScreen(QWidget):
    """Task list screen.

    When a ``db`` is attached every change (add / tick) is written to SQLite and
    the lists are re-read, so the screen survives a restart.  Without a database
    it falls back to the in-memory demo rows and stays clickable on its own.
    """

    go_back = pyqtSignal()

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user or {"id": 2, "full_name": "Marwan Hatem"}
        self.db = db

        self.assigned_tasks = [
            {"id": 101, "title": "Prepare Q3 sales report", "is_done": 0, "priority": "urgent"},
            {"id": 102, "title": "Review client contract", "is_done": 0, "priority": "normal"},
            {"id": 103, "title": "Update CRM records", "is_done": 1, "priority": "normal"},
        ]
        self.my_tasks = [
            {"id": 201, "title": "Read YOLO26 release notes", "is_done": 0, "priority": "normal"},
            {"id": 202, "title": "Buy coffee beans", "is_done": 0, "priority": "normal"},
        ]

        self._build_ui()
        # Belt and braces: load the real rows here too, so the screen is not
        # dependent on main.py injecting them.
        self._load_tasks_from_db()
        self._render_tasks()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Navigation belongs to the shell's sidebar, so this page keeps only an
        # in-page title row (with the open-task counter).
        root.addWidget(self._build_header())
        root.addWidget(self._divider())
        root.addWidget(self._build_scroll_area(), 1)
        root.addWidget(self._divider())
        root.addWidget(self._build_bottom_bar())

    @staticmethod
    def _divider():
        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        return line

    def _build_header(self):
        header = QFrame()
        header.setObjectName("Navbar")
        header.setFixedHeight(theme.NAVBAR_HEIGHT)

        row = QHBoxLayout(header)
        row.setContentsMargins(theme.SP_6, 0, theme.SP_6, 0)
        row.setSpacing(theme.SP_3)

        title = QLabel("📋  To Do List")
        title.setObjectName("H3")
        row.addWidget(title)
        row.addStretch(1)

        self.count_pill = QLabel("")
        self.count_pill.setObjectName("PillBadge")
        self.count_pill.setAlignment(Qt.AlignCenter)
        self.count_pill.setToolTip("Tasks that are not finished yet")
        row.addWidget(self.count_pill, 0, Qt.AlignVCenter)

        return header

    def _build_scroll_area(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("ScrollContent")

        layout = QVBoxLayout(content)
        layout.setContentsMargins(theme.SP_6, theme.SP_5, theme.SP_6, theme.SP_5)
        layout.setSpacing(theme.SP_2)

        self.assigned_header = QLabel("Assigned by Manager")
        self.assigned_header.setObjectName("SectionHeader")
        layout.addWidget(self.assigned_header)

        self.assigned_container = QVBoxLayout()
        self.assigned_container.setContentsMargins(0, 0, 0, 0)
        self.assigned_container.setSpacing(theme.SP_2)
        layout.addLayout(self.assigned_container)

        layout.addSpacing(theme.SP_5)

        self.mine_header = QLabel("My Tasks")
        self.mine_header.setObjectName("SectionHeaderAlt")
        layout.addWidget(self.mine_header)

        self.mine_container = QVBoxLayout()
        self.mine_container.setContentsMargins(0, 0, 0, 0)
        self.mine_container.setSpacing(theme.SP_2)
        layout.addLayout(self.mine_container)

        layout.addStretch(1)

        scroll.setWidget(content)
        return scroll

    def _build_bottom_bar(self):
        bar = QFrame()
        bar.setObjectName("Navbar")
        bar.setMinimumHeight(96)

        outer = QVBoxLayout(bar)
        outer.setContentsMargins(theme.SP_6, theme.SP_3, theme.SP_6, theme.SP_3)
        outer.setSpacing(theme.SP_2)

        row = QHBoxLayout()
        row.setSpacing(theme.SP_3)

        self.new_task_input = QLineEdit()
        self.new_task_input.setPlaceholderText("➕   Add a new task...")
        self.new_task_input.setMinimumHeight(theme.FIELD_HEIGHT)
        self.new_task_input.setClearButtonEnabled(True)
        self.new_task_input.returnPressed.connect(self._add_task)
        row.addWidget(self.new_task_input, 1)

        self.description_toggle = QPushButton("Description ▾")
        self.description_toggle.setObjectName("GhostButton")
        self.description_toggle.setMinimumHeight(theme.FIELD_HEIGHT)
        self.description_toggle.setCursor(Qt.PointingHandCursor)
        self.description_toggle.setToolTip("Add optional notes to the task")
        self.description_toggle.clicked.connect(self._toggle_description)
        row.addWidget(self.description_toggle)

        add_button = QPushButton("+  Add")
        add_button.setObjectName("PrimaryButton")
        add_button.setMinimumHeight(theme.FIELD_HEIGHT)
        add_button.setFixedWidth(150)
        add_button.setCursor(Qt.PointingHandCursor)
        add_button.clicked.connect(self._add_task)
        row.addWidget(add_button)

        hint = QLabel("Press Enter to add")
        hint.setObjectName("MutedLabel")
        row.addWidget(hint)
        outer.addLayout(row)

        self.new_task_description = QPlainTextEdit()
        self.new_task_description.setObjectName("TaskDescriptionInput")
        self.new_task_description.setPlaceholderText("Description (optional)…")
        self.new_task_description.setMinimumHeight(90)
        self.new_task_description.setStyleSheet("min-height: 90px;")
        self.new_task_description.setMaximumHeight(140)
        self.new_task_description.setVisible(False)
        outer.addWidget(self.new_task_description)

        return bar

    def _toggle_description(self):
        """Show / hide the optional description editor of the add bar."""
        show = not self.new_task_description.isVisible()
        self.new_task_description.setVisible(show)
        self.description_toggle.setText("Description ▴" if show else "Description ▾")
        if show:
            self.new_task_description.setFocus()

    # ------------------------------------------------------------------ #
    #  Rendering
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            else:
                child = item.layout()
                if child is not None:
                    TodoScreen._clear_layout(child)
                    child.deleteLater()

    def _task_row(self, task):
        row_frame = QFrame()
        row_frame.setObjectName("TaskRow")
        row_frame.setMinimumHeight(72)

        outer = QVBoxLayout(row_frame)
        outer.setContentsMargins(theme.SP_4, theme.SP_3, theme.SP_4, theme.SP_3)
        outer.setSpacing(theme.SP_1)

        row = QHBoxLayout()
        row.setSpacing(theme.SP_3)

        checkbox = QCheckBox()
        checkbox.setCursor(Qt.PointingHandCursor)
        checkbox.setChecked(bool(task.get("is_done")))
        checkbox.setToolTip("Mark as done")
        checkbox.toggled.connect(lambda _checked, t=task: self._toggle_task(t))
        row.addWidget(checkbox)

        title = QLabel(task.get("title", ""))
        title.setObjectName("TaskTitle")
        title.setProperty("done", "true" if task.get("is_done") else "false")
        title.setWordWrap(True)
        row.addWidget(title, 1)

        # Deadline badge: red when overdue, amber within 24 h, muted otherwise
        # (and always muted once the task is done).
        state = deadline_state(
            task.get("deadline_date"), task.get("deadline_time"),
            bool(task.get("is_done")),
        )
        if state != "none":
            badge = QLabel("\u23F0 " + format_deadline(
                task["deadline_date"], task.get("deadline_time")
            ))
            badge.setObjectName({
                "overdue": "PillUrgent",
                "soon": "PillDistracted",
            }.get(state, "PillMuted"))
            badge.setAlignment(Qt.AlignCenter)
            row.addWidget(badge)

        if task.get("priority") == "urgent":
            urgent = QLabel("URGENT")
            urgent.setObjectName("PillUrgent")
            urgent.setAlignment(Qt.AlignCenter)
            row.addWidget(urgent)

        if task.get("is_done"):
            done = QLabel("✓ Done")
            done.setObjectName("PillDone")
            done.setAlignment(Qt.AlignCenter)
            row.addWidget(done)

        outer.addLayout(row)

        description = (task.get("description") or "").strip()
        if description:
            note = QLabel(description)
            note.setObjectName("MutedLabel")
            note.setWordWrap(True)
            # line the note up with the title (checkbox + its spacing + row spacing)
            note.setContentsMargins(36 + theme.SP_3, 0, 0, 0)
            outer.addWidget(note)

        return row_frame

    def _empty_row(self, text="No tasks yet."):
        label = QLabel(text)
        label.setObjectName("EmptyLabel")
        return label

    def _empty_state(self):
        """Centered placeholder shown when there is nothing at all to list."""
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, theme.SP_10, 0, theme.SP_10)
        column.setSpacing(theme.SP_2)

        icon = QLabel("📭")
        icon.setObjectName("EmptyIcon")
        icon.setAlignment(Qt.AlignCenter)
        column.addWidget(icon)

        title = QLabel("No tasks yet")
        title.setObjectName("H3")
        title.setAlignment(Qt.AlignCenter)
        column.addWidget(title)

        hint = QLabel("Add your first task below.")
        hint.setObjectName("MutedLabel")
        hint.setAlignment(Qt.AlignCenter)
        column.addWidget(hint)

        return holder

    def _update_count_pill(self):
        if not hasattr(self, "count_pill"):
            return
        open_tasks = [t for t in self.assigned_tasks + self.my_tasks
                      if not t.get("is_done")]
        self.count_pill.setText(f"{len(open_tasks)} open")

    def _render_tasks(self):
        self._clear_layout(self.assigned_container)
        self._clear_layout(self.mine_container)

        both_empty = not self.assigned_tasks and not self.my_tasks
        self.assigned_header.setVisible(not both_empty)
        self.mine_header.setVisible(not both_empty)

        if both_empty:
            self.assigned_container.addWidget(self._empty_state())
            self._update_count_pill()
            return

        if self.assigned_tasks:
            for task in self.assigned_tasks:
                self.assigned_container.addWidget(self._task_row(task))
        else:
            self.assigned_container.addWidget(self._empty_row("No tasks assigned."))

        if self.my_tasks:
            for task in self.my_tasks:
                self.mine_container.addWidget(self._task_row(task))
        else:
            self.mine_container.addWidget(self._empty_row("No tasks yet."))

        self._update_count_pill()

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def refresh(self):
        """Re-read the tasks from the database (called when the page is shown)."""
        self._load_tasks_from_db()
        self._render_tasks()

    def _load_tasks_from_db(self):
        """Replace the demo rows with the rows stored in SQLite.

        Returns ``True`` when the database answered, even with two empty lists,
        so callers can fall back to the in-memory demo data when there is none.
        """
        if self.db is None or not self.user.get("id"):
            return False
        try:
            self.assigned_tasks = self.db.get_assigned_tasks(self.user["id"])
            self.my_tasks = self.db.get_self_tasks(self.user["id"])
        except Exception:
            logger.warning("Load failed", exc_info=True)
            return False
        return True

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _toggle_task(self, task):
        if self.db is not None:
            try:
                self.db.toggle_task(task["id"])
                # Re-read so the rendered row (strikethrough + "✓ Done" pill)
                # matches what was just written, including its new sort slot.
                self._load_tasks_from_db()
            except Exception:
                logger.warning("Toggle failed", exc_info=True)
        else:
            # No database: keep the previous in-memory behaviour.
            task["is_done"] = 0 if task.get("is_done") else 1
        self._render_tasks()

    def _add_task(self):
        text = self.new_task_input.text().strip()
        if not text:
            return

        description = self.new_task_description.toPlainText().strip()

        if self.db is not None:
            try:
                self.db.add_task(
                    user_id=self.user["id"],
                    title=text,
                    priority="normal",
                    assigned_by=None,
                    description=description or None,
                )
            except Exception:
                logger.warning("Add failed", exc_info=True)
                return
            # Reload from the database so the new row carries its real id.
            self._load_tasks_from_db()
        else:
            # No database: keep the previous in-memory behaviour.
            self.my_tasks.insert(
                0,
                {"id": 999, "title": text, "is_done": 0, "priority": "normal",
                 "description": description or None},
            )

        self.new_task_input.clear()
        self.new_task_description.clear()
        self.new_task_description.setVisible(False)
        self.description_toggle.setText("Description ▾")
        self._render_tasks()
