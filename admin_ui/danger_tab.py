"""Danger zone: destructive maintenance actions, each behind a typed phrase."""

import os
import shutil

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui import theme

CARD_ACTIONS = [
    {
        "title": "Delete all sessions and events",
        "description": "Removes every session and every event. Users and tasks "
                       "are preserved.",
        "button": "Delete all sessions",
        "phrase": "DELETE SESSIONS",
    },
    {
        "title": "Delete all tasks",
        "description": "Removes every task, both manager-assigned and personal.",
        "button": "Delete all tasks",
        "phrase": "DELETE TASKS",
    },
    {
        "title": "🔑  Reset all employee passwords to '1234'",
        "description": "Does not affect manager or admin accounts.",
        "button": "Reset passwords",
        "phrase": "RESET PASSWORDS",
    },
    {
        "title": "📤  Export database to file",
        "description": "Saves a copy of the SQLite DB.",
        "button": "Export...",
        "phrase": None,
    },
    {
        "title": "📥  Import database from file",
        "description": "Replaces the current DB with a backup file. The app must "
                       "be restarted after this.",
        "button": "Import...",
        "phrase": "IMPORT DATABASE",
    },
    {
        "title": "Factory reset (WIPE EVERYTHING)",
        "description": "Deletes every user except the two demo accounts (manager, "
                       "marwan), wipes all sessions, events, and tasks. Use this "
                       "before a demo.",
        "button": "Factory reset",
        "phrase": "FACTORY RESET",
    },
]


class DangerTab(QWidget):
    """Irreversible maintenance actions for demos and clean-up."""

    changed = pyqtSignal()
    database_replaced = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("ScrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_4)

        warning = QLabel(
            "⚠️  Every action on this page is permanent and asks you to type a "
            "confirmation phrase first."
        )
        warning.setObjectName("PillAbsent")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        for action in CARD_ACTIONS:
            layout.addWidget(self._build_card(action))

        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _build_card(self, action):
        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_5, theme.SP_5, theme.SP_5, theme.SP_5)
        layout.setSpacing(theme.SP_2)

        title = QLabel(action["title"])
        title.setObjectName("H3")
        layout.addWidget(title)

        description = QLabel(action["description"])
        description.setObjectName("MutedLabel")
        description.setWordWrap(True)
        layout.addWidget(description)

        if action["phrase"]:
            phrase = QLabel(f"Requires typing:  {action['phrase']}")
            phrase.setObjectName("SecondaryLabel")
            layout.addWidget(phrase)

        row = QHBoxLayout()
        row.addStretch(1)
        button = QPushButton(action["button"])
        button.setObjectName("DangerButton")
        button.setMinimumHeight(44)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(
            lambda _checked=False, key=action["title"]: self._run(key)
        )
        row.addWidget(button)
        layout.addLayout(row)
        return card

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    def _confirm(self, phrase, description):
        """Ask for a typed phrase; returns True only on an exact match."""
        text, accepted = QInputDialog.getText(
            self, "Confirm destructive action",
            f"{description}\n\nType {phrase!r} to confirm:",
        )
        if not accepted:
            return False
        if text.strip() != phrase:
            QMessageBox.information(self, "Aborted",
                                    "The phrase did not match — nothing was changed.")
            return False
        return True

    def _run(self, title):
        handler = {
            CARD_ACTIONS[0]["title"]: self._delete_sessions,
            CARD_ACTIONS[1]["title"]: self._delete_tasks,
            CARD_ACTIONS[2]["title"]: self._reset_passwords,
            CARD_ACTIONS[3]["title"]: self._export,
            CARD_ACTIONS[4]["title"]: self._import,
            CARD_ACTIONS[5]["title"]: self._factory_reset,
        }.get(title)
        if handler is not None:
            handler()

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _delete_sessions(self):
        answer = QMessageBox.question(
            self, "Delete all sessions",
            "Delete every session and every event? Users and tasks are kept.",
            QMessageBox.Cancel | QMessageBox.Yes, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        if not self._confirm("DELETE SESSIONS", "This removes all session history."):
            return
        try:
            removed = self.db.delete_sessions_filtered()
        except Exception as error:
            QMessageBox.critical(self, "Could not delete the sessions",
                                 f"The transaction was rolled back:\n{error}")
            return
        self.changed.emit()
        QMessageBox.information(
            self, "Sessions deleted",
            "Removed %d session(s) and %d event(s)."
            % (removed["sessions"], removed["events"]),
        )

    def _delete_tasks(self):
        if not self._confirm("DELETE TASKS", "This removes every task."):
            return
        try:
            removed = self.db.delete_all_tasks()
        except Exception as error:
            QMessageBox.critical(self, "Could not delete the tasks",
                                 f"The database refused the delete:\n{error}")
            return
        self.changed.emit()
        QMessageBox.information(self, "Tasks deleted", f"Removed {removed} task(s).")

    def _reset_passwords(self):
        if not self._confirm("RESET PASSWORDS",
                             "Every employee password becomes '1234'."):
            return
        try:
            changed = self.db.reset_employee_passwords("1234")
        except Exception as error:
            QMessageBox.critical(self, "Could not reset the passwords",
                                 f"The database refused the update:\n{error}")
            return
        self.changed.emit()
        QMessageBox.information(
            self, "Passwords reset",
            f"{changed} employee account(s) now use the password '1234'.",
        )

    def _export(self):
        default = os.path.join(os.path.dirname(self.db.db_path), "admin_backup.db")
        path, _selected = QFileDialog.getSaveFileName(
            self, "Export database", default, "SQLite database (*.db *.sqlite)"
        )
        if not path:
            return
        try:
            self.db.export_database(path)
        except Exception as error:
            QMessageBox.critical(self, "Export failed",
                                 f"Could not write the copy:\n{error}")
            return
        QMessageBox.information(self, "Export complete",
                                f"Database copied to:\n{path}")

    def _import(self):
        path, _selected = QFileDialog.getOpenFileName(
            self, "Import database", os.path.dirname(self.db.db_path),
            "SQLite database (*.db *.sqlite);;All files (*)",
        )
        if not path:
            return
        if not self._confirm(
            "IMPORT DATABASE",
            "The current database is replaced by the selected file.",
        ):
            return
        try:
            shutil.copyfile(self.db.db_path, self.db.db_path + ".pre-import")
            self.db.import_database(path)
        except Exception as error:
            QMessageBox.critical(self, "Import failed",
                                 f"The database could not be replaced:\n{error}")
            return
        self.database_replaced.emit()
        self.changed.emit()
        answer = QMessageBox.information(
            self, "Import complete",
            "The database was replaced (a copy of the previous file was kept as "
            "*.pre-import).\n\nThe application must be restarted.\n\n"
            "Close the admin panel now?",
            QMessageBox.Close | QMessageBox.Cancel, QMessageBox.Close,
        )
        if answer == QMessageBox.Close:
            window = self.window()
            if window is not None:
                window.close()

    def _factory_reset(self):
        if not self._confirm(
            "FACTORY RESET",
            "Everything is deleted except the two demo accounts (manager, marwan).",
        ):
            return
        try:
            self.db.factory_reset()
        except Exception as error:
            QMessageBox.critical(self, "Factory reset failed",
                                 f"The transaction was rolled back:\n{error}")
            return
        counts = self.db.table_counts()
        self.changed.emit()
        QMessageBox.information(
            self, "Factory reset complete",
            "users=%d  sessions=%d  events=%d  tasks=%d"
            % (counts["users"], counts["sessions"], counts["events"], counts["tasks"]),
        )
