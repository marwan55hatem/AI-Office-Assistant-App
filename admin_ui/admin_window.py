"""Admin panel shell: top bar, five tabs and a row-count status bar."""

import logging
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from admin_ui.danger_tab import DangerTab
from admin_ui.events_tab import EventsTab
from admin_ui.sessions_tab import SessionsTab
from admin_ui.tasks_tab import TasksTab
from admin_ui.users_tab import UsersTab
from ui import theme

logger = logging.getLogger(__name__)


class AdminWindow(QMainWindow):
    """Standalone developer tool over the application's SQLite database."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        self.setWindowTitle("🔐 Admin Panel — Desktop AI Office Assistant")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 700)

        try:
            self._db_label_text = os.path.relpath(db.db_path, db.BASE_DIR)
        except Exception:
            self._db_label_text = str(getattr(db, "db_path", "database"))

        self._build_ui()
        self._update_counts()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_top_bar())

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.users_tab = UsersTab(self.db)
        self.sessions_tab = SessionsTab(self.db)
        self.events_tab = EventsTab(self.db)
        self.tasks_tab = TasksTab(self.db)
        self.danger_tab = DangerTab(self.db)

        self.tabs.addTab(self.users_tab, "🧑  Users")
        self.tabs.addTab(self.sessions_tab, "📊  Sessions")
        self.tabs.addTab(self.events_tab, "📝  Events")
        self.tabs.addTab(self.tasks_tab, "✅  Tasks")
        self.tabs.addTab(self.danger_tab, "⚠️  Danger")

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(
            theme.SP_5, theme.SP_4, theme.SP_5, theme.SP_2
        )
        wrapper_layout.addWidget(self.tabs)
        layout.addWidget(wrapper, 1)

        layout.addWidget(self._build_status_bar())

        # Any tab that mutates rows refreshes the counters (and the sibling
        # tabs' filter combos, which depend on the users table).
        for tab in (self.users_tab, self.sessions_tab, self.events_tab,
                    self.tasks_tab, self.danger_tab):
            tab.changed.connect(self._on_changed)

    def _build_top_bar(self):
        bar = QFrame()
        bar.setObjectName("Navbar")
        bar.setFixedHeight(theme.NAVBAR_HEIGHT)

        row = QHBoxLayout(bar)
        row.setContentsMargins(theme.SP_6, 0, theme.SP_6, 0)
        row.setSpacing(theme.SP_3)

        title = QLabel("🔐  Admin Panel")
        title.setObjectName("H3")
        row.addWidget(title)

        row.addStretch(1)

        self.db_label = QLabel(f"Connected to: {self._db_label_text}")
        self.db_label.setObjectName("MutedLabel")
        row.addWidget(self.db_label)

        row.addStretch(1)

        logout = QPushButton("Logout")
        logout.setObjectName("GhostButton")
        logout.setCursor(Qt.PointingHandCursor)
        logout.setToolTip("Close the admin panel")
        logout.clicked.connect(self.close)
        row.addWidget(logout)

        return bar

    def _build_status_bar(self):
        bar = QFrame()
        bar.setObjectName("Navbar")
        bar.setFixedHeight(52)

        row = QHBoxLayout(bar)
        row.setContentsMargins(theme.SP_6, 0, theme.SP_6, 0)

        self.counts_label = QLabel("")
        self.counts_label.setObjectName("MutedLabel")
        row.addWidget(self.counts_label)
        row.addStretch(1)

        return bar

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def _on_changed(self):
        """A tab changed the data: refresh the counters and the filter combos."""
        self._update_counts()
        current = self.tabs.currentWidget()
        for tab in (self.sessions_tab, self.events_tab, self.tasks_tab):
            if tab is not current:
                try:
                    tab.refresh_users()
                except Exception:
                    logger.warning("Could not refresh the user list of a tab", exc_info=True)

    def _update_counts(self):
        try:
            counts = self.db.table_counts()
        except Exception:
            self.counts_label.setText("Row counts unavailable")
            logger.warning("table_counts failed", exc_info=True)
            return
        self.counts_label.setText(
            "users %d   ·   sessions %d   ·   events %d   ·   tasks %d"
            % (counts["users"], counts["sessions"], counts["events"],
               counts["tasks"])
        )

    def closeEvent(self, event):
        """Just close: the database connection is shared and closed by the app."""
        event.accept()
