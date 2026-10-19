"""Signup screen -- employees request an account, a manager approves it.

The screen never creates a usable account directly: it stores a *pending*
request through :meth:`DatabaseManager.create_signup_request`, and the manager
dashboard decides whether the account becomes active.
"""

import logging
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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

MIN_PASSWORD_LENGTH = 4


class SignupScreen(QWidget):
    """Centered "Create Account" card that files a pending signup request."""

    go_back = pyqtSignal()
    signup_done = pyqtSignal()

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self.db = db
        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        outer.addStretch(1)
        outer.addWidget(self._build_card(), 0, Qt.AlignHCenter)
        outer.addStretch(1)

    def _build_card(self):
        card, layout = build_auth_card(self, margins=(48, 24, 48, 28))
        self._add_back_button(layout)
        add_brand(layout, "users", "Create Account", "Your manager will review your request", wrap_subtitle=True)
        layout.addSpacing(theme.SP_4)
        self._add_fields(layout)
        layout.addLayout(self._build_strength_bar())
        self.error_label = make_error_label()
        layout.addWidget(self.error_label)
        layout.addSpacing(theme.SP_1)
        self.submit_button = make_primary_button("Submit Request", self._on_submit)
        layout.addWidget(self.submit_button)
        add_centered_note(layout, "Your manager will review your request shortly.", wrap=True)
        add_centered_note(layout, FOOTER_TEXT)
        return card

    def _add_back_button(self, layout):
        """The back arrow in the top-left corner of the card."""
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        self.back_button = QPushButton("←")
        self.back_button.setObjectName("IconButton")
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.setToolTip("Back to login")
        self.back_button.clicked.connect(lambda: self.go_back.emit())
        top_row.addWidget(self.back_button)
        top_row.addStretch(1)
        layout.addLayout(top_row)

    def _add_fields(self, layout):
        """Full name, username, password and its confirmation."""
        self.full_name_input = make_input("🧑  Full name")
        self.username_input = make_input("🏷   Username")
        self.password_input = make_input("🔒  Password", password=True)
        self.password_input.textChanged.connect(self._update_strength)
        self.confirm_input = make_input("🔒  Confirm password", password=True)
        self.confirm_input.returnPressed.connect(self._on_submit)
        for field in (self.full_name_input, self.username_input, self.password_input, self.confirm_input):
            layout.addWidget(field)

    def _build_strength_bar(self):
        """Three-segment password strength hint (cosmetic only)."""
        row = QHBoxLayout()
        row.setSpacing(theme.SP_1)

        self.strength_segments = []
        for _ in range(3):
            segment = QFrame()
            segment.setObjectName("BarTrack")
            segment.setFixedHeight(6)
            segment.setStyleSheet(
                "QFrame { background-color: %s; border: none; border-radius: 3px; }"
                % theme.ELEVATED
            )
            row.addWidget(segment, 1)
            self.strength_segments.append(segment)

        self.strength_label = QLabel("")
        self.strength_label.setObjectName("MutedLabel")
        row.addWidget(self.strength_label)

        self._update_strength()
        return row

    def _update_strength(self, *_args):
        """Colour the segments by password length: >=4 / >=8 / >=12."""
        if not hasattr(self, "strength_segments"):
            return
        length = len(self.password_input.text())
        score = 0
        if length >= 12:
            score = 3
        elif length >= 8:
            score = 2
        elif length >= MIN_PASSWORD_LENGTH:
            score = 1

        colours = {0: theme.ELEVATED, 1: theme.DANGER, 2: theme.WARNING, 3: theme.SUCCESS}
        for index, segment in enumerate(self.strength_segments):
            filled = index < score
            segment.setStyleSheet(
                "QFrame { background-color: %s; border: none; border-radius: 3px; }"
                % (colours[score] if filled else theme.ELEVATED)
            )
        self.strength_label.setText(
            {0: "", 1: "weak", 2: "good", 3: "strong"}[score]
        )

    # ------------------------------------------------------------------ #
    #  Logic
    # ------------------------------------------------------------------ #
    def _show_error(self, message):
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self):
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _clear_fields(self):
        self.full_name_input.clear()
        self.username_input.clear()
        self.password_input.clear()
        self.confirm_input.clear()

    def _on_submit(self):
        full_name = self.full_name_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        confirm = self.confirm_input.text().strip()

        if not full_name or not username or not password or not confirm:
            self._show_error("Please fill in all fields")
            return
        if password != confirm:
            self._show_error("Passwords do not match")
            return
        if len(password) < MIN_PASSWORD_LENGTH:
            self._show_error(
                "Password must be at least %d characters" % MIN_PASSWORD_LENGTH
            )
            return

        if self.db is None:
            self._show_error("Database not available")
            return

        try:
            ok, message = self.db.create_signup_request(username, password, full_name)
        except Exception:
            # e.g. a locked database: report it instead of crashing the screen.
            logger.warning("could not save the request", exc_info=True)
            self._show_error("Could not save your request. Please try again.")
            return

        if not ok:
            self._show_error(message)
            return

        self._clear_error()
        self._clear_fields()

        QMessageBox.information(
            self,
            "Request Submitted",
            "Your signup request was submitted.\n"
            "A manager will review it shortly.",
        )
        self.signup_done.emit()
