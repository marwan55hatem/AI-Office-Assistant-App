"""Standalone admin password prompt (independent of the app's login screen)."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui import theme

#: Developer-only password.  Case-sensitive.
ADMIN_PASSWORD = "admin123"


class AdminLoginDialog(QDialog):
    """Small centred card asking for the admin password."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔐 Admin Access")
        self.setFixedSize(560, 360)
        self.setObjectName("AdminLogin")
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("Card")
        theme.apply_card_shadow(card)
        outer.addWidget(card)

        shell = QVBoxLayout(card)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        accent = QFrame()
        accent.setObjectName("AccentBar")
        accent.setFixedHeight(4)
        shell.addWidget(accent)

        body = QWidget()
        shell.addWidget(body)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(theme.SP_8, theme.SP_6, theme.SP_8, theme.SP_6)
        layout.setSpacing(theme.SP_3)

        title = QLabel("🔐  Admin Access")
        title.setObjectName("H1")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("Developer tool — enter the admin password to continue.")
        hint.setObjectName("SecondaryLabel")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addSpacing(theme.SP_2)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("🔒  Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(theme.FIELD_HEIGHT)
        self.password_input.returnPressed.connect(self._on_unlock)
        layout.addWidget(self.password_input)

        layout.addSpacing(theme.SP_1)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP_3)

        self.enter_button = QPushButton("Enter")
        self.enter_button.setObjectName("GhostButton")
        self.enter_button.setMinimumHeight(54)
        self.enter_button.setCursor(Qt.PointingHandCursor)
        self.enter_button.clicked.connect(self.accept)

        self.unlock_button = QPushButton("Unlock")
        self.unlock_button.setObjectName("PrimaryButton")
        self.unlock_button.setMinimumHeight(54)
        self.unlock_button.setCursor(Qt.PointingHandCursor)
        self.unlock_button.setDefault(True)
        self.unlock_button.clicked.connect(self._on_unlock)

        buttons.addWidget(self.enter_button, 1)
        buttons.addWidget(self.unlock_button, 1)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------ #
    #  Behaviour
    # ------------------------------------------------------------------ #
    def _on_unlock(self):
        """Accept on the right password, warn and clear otherwise."""
        if self.password_input.text() == ADMIN_PASSWORD:
            self.accept()
            return
        QMessageBox.warning(self, "Wrong password", "That password is not correct.")
        self.password_input.clear()
        self.password_input.setFocus()
