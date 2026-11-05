"""Login screen -- the entry point of the application.

The screen is deliberately database free: when ``db`` is ``None`` (demo mode)
any non-empty e-mail/password combination signs the user in.  If a ``db``
object is supplied it must expose ``sign_in(identifier, password, remember)``,
which returns ``(user, None)`` or ``(None, message)``.  The role comes from the
account, so there is no Manager / Employee choice any more.
"""

import logging
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QCheckBox, QPushButton, QVBoxLayout, QWidget

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
    """Centered sign-in card: e-mail, password and "keep me signed in"."""

    login_success = pyqtSignal(str)
    signup_requested = pyqtSignal()

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self.db = db
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
        self._add_credentials(layout)
        layout.addSpacing(theme.SP_1)
        self._add_actions(layout)
        layout.addSpacing(theme.SP_2)
        add_centered_note(layout, FOOTER_TEXT)
        return card

    def _add_credentials(self, layout):
        """E-mail, password, "keep me signed in" and the (hidden) error message."""
        self.username_input = make_input("✉  Work e-mail")
        self.username_input.setClearButtonEnabled(True)
        layout.addWidget(self.username_input)

        self.password_input = make_input("🔒  Password", password=True)
        self.password_input.returnPressed.connect(self._on_login)
        layout.addWidget(self.password_input)

        self.remember_checkbox = QCheckBox("Keep me signed in on this computer")
        self.remember_checkbox.setChecked(True)
        self.remember_checkbox.setToolTip(
            "Stores a sign-in token in Windows Credential Manager (never your password)")
        layout.addWidget(self.remember_checkbox)

        self.error_label = make_error_label()
        layout.addWidget(self.error_label)

    def _add_actions(self, layout):
        """The Login button and the link to the join form."""
        self.login_button = make_primary_button("Login", self._on_login)
        self.login_button.setStyleSheet("font-size: 16px;")
        self.login_button.setDefault(True)
        layout.addWidget(self.login_button)

        layout.addSpacing(theme.SP_1)

        self.signup_button = QPushButton("New here?  Join your company")
        self.signup_button.setObjectName("GhostButton")
        self.signup_button.setCursor(Qt.PointingHandCursor)
        self.signup_button.setToolTip("Request an account with your company code or invite link")
        self.signup_button.clicked.connect(lambda: self.signup_requested.emit())
        layout.addWidget(self.signup_button)

    # ------------------------------------------------------------------ #
    #  Logic
    # ------------------------------------------------------------------ #
    def _show_error(self, message):
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self):
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _on_login(self):
        identifier = self.username_input.text().strip()
        password = self.password_input.text()      # passwords are used exactly as typed

        if not identifier or not password:
            self._show_error("Please enter your e-mail and password")
            return

        # No database attached (UI-only demo): accept any non-empty credentials.
        if self.db is None:
            self._clear_error()
            self.login_success.emit("employee")
            return

        self.login_button.setEnabled(False)
        try:
            user, message = self.db.sign_in(identifier, password, self.remember_checkbox.isChecked())
        except Exception:
            # A missing/locked database must not take the login screen down.
            logger.warning("sign-in failed", exc_info=True)
            user, message = None, "Could not sign in. Please try again."
        finally:
            self.login_button.setEnabled(True)
            self.password_input.clear()

        if user is None:
            self._show_error(message or "Invalid credentials")
            return

        self.logged_in_user = user
        self._clear_error()
        self.login_success.emit(user["role"])
