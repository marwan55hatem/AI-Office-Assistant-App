"""Login screen -- the entry point of the application.

The screen is deliberately database free: when ``db`` is ``None`` (demo mode)
any non-empty username/password combination signs the user in.  If a ``db``
object is supplied it must expose ``get_user(username, password, role)``.
"""

import logging
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.auth_form import (
    FOOTER_TEXT,
    add_brand,
    add_centered_note,
    build_auth_card,
    make_error_label,
    make_input,
    make_primary_button,
)


logger = logging.getLogger(__name__)


class LoginScreen(QWidget):
    """Centered login card with a Manager / Employee role toggle."""

    login_success = pyqtSignal(str)
    signup_requested = pyqtSignal()

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.selected_role = "employee"
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 12, 24, 12)
        outer.addStretch(1)
        outer.addWidget(self._build_card(), 0, Qt.AlignHCenter)
        outer.addStretch(1)

    def _build_card(self):
        card, layout = build_auth_card(self, margins=(48, 28, 48, 30))
        add_brand(layout, "bot", "Desktop AI Office Assistant", "Sign in to continue", wrap_title=True)
        layout.addSpacing(theme.SP_4)
        layout.addLayout(self._build_role_row())
        layout.addSpacing(theme.SP_2)
        self._add_credentials(layout)
        layout.addSpacing(theme.SP_1)
        self._add_actions(layout)
        layout.addSpacing(theme.SP_2)
        add_centered_note(layout, FOOTER_TEXT)
        return card

    def _add_credentials(self, layout):
        """Username, password and the (hidden) error message."""
        self.username_input = make_input("🧑  Username")
        self.username_input.setClearButtonEnabled(True)
        layout.addWidget(self.username_input)

        self.password_input = make_input("🔒  Password", password=True)
        self.password_input.returnPressed.connect(self._on_login)
        layout.addWidget(self.password_input)

        self.error_label = make_error_label()
        layout.addWidget(self.error_label)

    def _add_actions(self, layout):
        """The Login button and the link to the sign-up form."""
        self.login_button = make_primary_button("Login", self._on_login)
        self.login_button.setStyleSheet("font-size: 16px;")
        self.login_button.setDefault(True)
        layout.addWidget(self.login_button)

        layout.addSpacing(theme.SP_1)

        self.signup_button = QPushButton("Don't have an account?  Sign up")
        self.signup_button.setObjectName("GhostButton")
        self.signup_button.setCursor(Qt.PointingHandCursor)
        self.signup_button.setToolTip("Request an employee account")
        self.signup_button.clicked.connect(lambda: self.signup_requested.emit())
        layout.addWidget(self.signup_button)

    def _build_role_row(self):
        row = QHBoxLayout()
        row.setSpacing(theme.SP_3)

        self.role_group = QButtonGroup(self)
        self.role_group.setExclusive(True)

        self.manager_button = QPushButton("👔  Manager")
        self.manager_button.setObjectName("RoleButton")
        self.manager_button.setCheckable(True)
        self.manager_button.setCursor(Qt.PointingHandCursor)
        self.manager_button.setMinimumHeight(theme.FIELD_HEIGHT)

        self.employee_button = QPushButton("🧑  Employee")
        self.employee_button.setObjectName("RoleButton")
        self.employee_button.setCheckable(True)
        self.employee_button.setCursor(Qt.PointingHandCursor)
        self.employee_button.setMinimumHeight(theme.FIELD_HEIGHT)
        self.employee_button.setChecked(True)

        self.role_group.addButton(self.manager_button)
        self.role_group.addButton(self.employee_button)

        self.manager_button.clicked.connect(lambda: self._set_role("manager"))
        self.employee_button.clicked.connect(lambda: self._set_role("employee"))

        # Equal width halves.
        row.addWidget(self.manager_button, 1)
        row.addWidget(self.employee_button, 1)
        return row

    # ------------------------------------------------------------------ #
    #  Logic
    # ------------------------------------------------------------------ #
    def _set_role(self, role):
        self.selected_role = role
        theme.repolish(self.manager_button)
        theme.repolish(self.employee_button)

    def _show_error(self, message):
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self):
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _on_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            self._show_error("Please enter username and password")
            return

        # No database attached (UI-only demo): accept any non-empty credentials.
        if self.db is None:
            self._clear_error()
            self.login_success.emit(self.selected_role)
            return

        try:
            user = self.db.get_user(username, password, self.selected_role)
        except Exception:
            # A missing/locked database must not take the login screen down.
            logger.warning("database lookup failed", exc_info=True)
            self._show_error("Could not read the user database. Please try again.")
            return

        if user is None:
            self._show_error("Invalid credentials")
            return

        # A signup request must be approved by a manager before it can log in.
        status = user.get("status", "approved")
        if status == "pending":
            self._show_error("⏳ Your account is waiting for manager approval")
            return
        if status == "rejected":
            self._show_error("🚫 Your signup request was rejected")
            return

        self.logged_in_user = user
        self._clear_error()
        self.login_success.emit(self.selected_role)
