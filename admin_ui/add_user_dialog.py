"""Dialogs for creating and editing user accounts from the admin panel."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ui import theme

ROLES = [("manager", "👔  Manager"), ("employee", "🧑  Employee")]
STATUSES = [("approved", "✅  Approved"), ("pending", "⏳  Pending"),
            ("rejected", "🚫  Rejected")]


class _UserFormDialog(QDialog):
    """Shared form: username, password, full name, role and status segments."""

    def __init__(self, title, submit_label, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self.created_id = None
        self.setObjectName("UserForm")

        card = QFrame(self)
        card.setObjectName("Card")
        theme.apply_card_shadow(card)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        layout.setSpacing(theme.SP_3)

        heading = QLabel(title)
        heading.setObjectName("H2")
        layout.addWidget(heading)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("🏷   Username")
        self.username_input.setMinimumHeight(theme.FIELD_HEIGHT)
        layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("🔒  Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(theme.FIELD_HEIGHT)
        layout.addWidget(self.password_input)

        self.full_name_input = QLineEdit()
        self.full_name_input.setPlaceholderText("🧑  Full name")
        self.full_name_input.setMinimumHeight(theme.FIELD_HEIGHT)
        layout.addWidget(self.full_name_input)

        layout.addWidget(self._caption("Role"))
        self.role_buttons = self._segment_row(
            layout, ROLES, "role", default="employee"
        )

        layout.addWidget(self._caption("Status"))
        self.status_buttons = self._segment_row(
            layout, STATUSES, "status", default="approved"
        )

        layout.addSpacing(theme.SP_2)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SP_3)

        cancel = QPushButton("Cancel")
        cancel.setObjectName("GhostButton")
        cancel.setMinimumHeight(54)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)

        self.submit_button = QPushButton(submit_label)
        self.submit_button.setObjectName("PrimaryButton")
        self.submit_button.setMinimumHeight(54)
        self.submit_button.setCursor(Qt.PointingHandCursor)
        self.submit_button.clicked.connect(self._on_submit)

        buttons.addWidget(cancel, 1)
        buttons.addWidget(self.submit_button, 1)
        layout.addLayout(buttons)

    @staticmethod
    def _caption(text):
        label = QLabel(text.upper())
        label.setObjectName("SectionHeaderSmall")
        return label

    def _segment_row(self, layout, options, group_name, default):
        row = QHBoxLayout()
        row.setSpacing(theme.SP_2)
        group = QButtonGroup(self)
        group.setExclusive(True)
        buttons = {}
        for value, label in options:
            button = QPushButton(label)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumHeight(48)
            button.clicked.connect(
                lambda _checked=False, name=group_name: self._select(name)
            )
            group.addButton(button)
            row.addWidget(button, 1)
            buttons[value] = button
        buttons[default].setChecked(True)
        layout.addLayout(row)
        setattr(self, f"_{group_name}_group", group)
        return buttons

    def _select(self, group_name):
        for button in getattr(self, f"_{group_name}_group").buttons():
            theme.repolish(button)

    def selected_role(self):
        """The role chosen in the dialog: 'employee' or 'manager'."""
        for value, button in self.role_buttons.items():
            if button.isChecked():
                return value
        return "employee"

    def selected_status(self):
        """The account status chosen in the dialog: 'approved' or 'pending'."""
        for value, button in self.status_buttons.items():
            if button.isChecked():
                return value
        return "approved"

    def _on_submit(self):
        raise NotImplementedError


class AddUserDialog(_UserFormDialog):
    """Create a user directly (bypassing the signup/approval flow)."""

    def __init__(self, db, parent=None):
        super().__init__("+  Add User", "Add User", parent=parent)
        self.db = db

    def _on_submit(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()
        full_name = self.full_name_input.text().strip()

        if not username or not password or not full_name:
            QMessageBox.warning(
                self, "Missing details",
                "Username, password and full name are all required.",
            )
            return

        try:
            if self.db.username_taken(username):
                QMessageBox.warning(
                    self, "Username taken",
                    f"'{username}' already exists. Pick another username.",
                )
                return

            self.created_id = self.db.create_user(
                username, password, self.selected_role(), full_name, self.selected_status())
        except Exception as error:
            QMessageBox.critical(
                self, "Could not add the user",
                f"The database refused the insert:\n{error}",
            )
            return

        self.accept()


class EditUserDialog(_UserFormDialog):
    """Edit an existing user; an empty password field keeps the current one."""

    def __init__(self, db, user, parent=None):
        super().__init__(f"✏️  Edit {user['username']}", "Save Changes", parent=parent)
        self.db = db
        self.user = user

        self.username_input.setText(user["username"])
        self.full_name_input.setText(user["full_name"])
        self.password_input.setPlaceholderText("🔒  New password (leave empty to keep)")
        self.role_buttons[user["role"]].setChecked(True)
        self.status_buttons[user.get("status", "approved")].setChecked(True)
        for button in list(self.role_buttons.values()) + list(self.status_buttons.values()):
            theme.repolish(button)

    def _on_submit(self):
        username = self.username_input.text().strip()
        full_name = self.full_name_input.text().strip()
        password = self.password_input.text()

        if not username or not full_name:
            QMessageBox.warning(
                self, "Missing details", "Username and full name cannot be empty."
            )
            return

        try:
            if self.db.username_taken(username, except_user_id=self.user["id"]):
                QMessageBox.warning(
                    self, "Username taken",
                    f"'{username}' belongs to another account.",
                )
                return

            self.db.update_user(
                self.user["id"],
                username=username,
                full_name=full_name,
                role=self.selected_role(),
                status=self.selected_status(),
                password=password or None,
            )
        except Exception as error:
            QMessageBox.critical(
                self, "Could not save the user",
                f"The database refused the update:\n{error}",
            )
            return

        self.accept()
