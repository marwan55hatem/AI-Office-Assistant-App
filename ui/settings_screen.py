"""Settings screen: profile, password and appearance (dark / light theme).

The page is shared by the manager and the employee shell.  It talks to the
database only through :meth:`DatabaseManager.update_user_profile` and
:meth:`DatabaseManager.update_user_password`, and switches the application theme
through :func:`ui.theme.apply_theme` (which also remembers the choice).
"""

import logging
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from llm import status as model_status
from ui import preferences, theme
from ui.widgets import make_card

logger = logging.getLogger(__name__)

APP_NAME = "Desktop AI Office Assistant"
APP_VERSION = "1.0.0"
MIN_PASSWORD_LENGTH = 10       # same rule as the online server
CONTENT_MAX_WIDTH = 920


class SettingsScreen(QWidget):
    """Profile + password + appearance + about, one card each."""

    #: Emitted after a successful profile save: ``(full_name, username)``.
    profile_updated = pyqtSignal(str, str)

    def __init__(self, user=None, db=None, parent=None):
        super().__init__(parent)
        self.user = user if user is not None else {"id": 2, "full_name": "Marwan Hatem"}
        self.db = db

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("ScrollContent")
        outer = QHBoxLayout(content)
        outer.setContentsMargins(theme.SP_6, theme.SP_6, theme.SP_6, theme.SP_6)
        outer.addStretch(1)

        column = QWidget()
        column.setMaximumWidth(CONTENT_MAX_WIDTH)
        column.setMinimumWidth(480)
        body = QVBoxLayout(column)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(theme.SP_5)
        body.addWidget(self._build_profile_card())
        body.addWidget(self._build_password_card())
        body.addWidget(self._build_appearance_card())
        body.addWidget(self._build_ai_card())
        self.email_card = self._build_email_card()
        body.addWidget(self.email_card)
        body.addWidget(self._build_about_card())
        body.addStretch(1)

        outer.addWidget(column, 100)
        outer.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _build_header(self):
        header = QFrame()
        header.setObjectName("Navbar")
        header.setFixedHeight(theme.NAVBAR_HEIGHT)

        row = QHBoxLayout(header)
        row.setContentsMargins(theme.SP_6, 0, theme.SP_6, 0)

        title = QLabel("⚙️  Settings")
        title.setObjectName("H3")
        row.addWidget(title)
        row.addStretch(1)
        return header

    @staticmethod
    def _caption(text):
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    @staticmethod
    def _status_label():
        label = QLabel("")
        label.setObjectName("ErrorLabel")
        label.setWordWrap(True)
        label.setVisible(False)
        return label

    @staticmethod
    def _show_status(label, message, ok):
        label.setObjectName("SuccessLabel" if ok else "ErrorLabel")
        theme.repolish(label)
        label.setText(message)
        label.setVisible(True)

    # ------------------------------ profile ---------------------------- #
    def _build_profile_card(self):
        card, layout = make_card("🧑  Profile")

        identity = QHBoxLayout()
        identity.setSpacing(theme.SP_4)

        self.avatar = QLabel("?")
        self.avatar.setObjectName("AvatarLarge")
        self.avatar.setFixedSize(64, 64)
        self.avatar.setAlignment(Qt.AlignCenter)
        identity.addWidget(self.avatar)

        names = QVBoxLayout()
        names.setSpacing(theme.SP_1)
        self.identity_name = QLabel("")
        self.identity_name.setObjectName("H3")
        names.addWidget(self.identity_name)

        self.role_pill = QLabel("")
        self.role_pill.setAlignment(Qt.AlignCenter)
        names.addWidget(self.role_pill, 0, Qt.AlignLeft)
        identity.addLayout(names)
        identity.addStretch(1)
        layout.addLayout(identity)

        layout.addSpacing(theme.SP_2)
        layout.addWidget(self._caption("Full name"))
        self.full_name_input = QLineEdit()
        self.full_name_input.setMinimumHeight(theme.FIELD_HEIGHT)
        layout.addWidget(self.full_name_input)

        layout.addWidget(self._caption("Username"))
        self.username_input = QLineEdit()
        self.username_input.setMinimumHeight(theme.FIELD_HEIGHT)
        self.username_input.returnPressed.connect(self._on_save_profile)
        layout.addWidget(self.username_input)

        self.profile_status = self._status_label()
        layout.addWidget(self.profile_status)

        self.save_profile_button = QPushButton("Save Profile")
        self.save_profile_button.setObjectName("PrimaryButton")
        self.save_profile_button.setMinimumHeight(54)
        self.save_profile_button.setStyleSheet("font-size: 16px;")
        self.save_profile_button.setCursor(Qt.PointingHandCursor)
        self.save_profile_button.clicked.connect(self._on_save_profile)
        layout.addWidget(self.save_profile_button)
        return card

    # ------------------------------ password --------------------------- #
    def _build_password_card(self):
        card, layout = make_card("🔒  Change Password")

        layout.addWidget(self._caption("Current password"))
        self.current_password_input = QLineEdit()
        self.current_password_input.setEchoMode(QLineEdit.Password)
        self.current_password_input.setMinimumHeight(theme.FIELD_HEIGHT)
        layout.addWidget(self.current_password_input)

        layout.addWidget(self._caption("New password"))
        self.new_password_input = QLineEdit()
        self.new_password_input.setEchoMode(QLineEdit.Password)
        self.new_password_input.setMinimumHeight(theme.FIELD_HEIGHT)
        self.new_password_input.textChanged.connect(self._update_strength)
        layout.addWidget(self.new_password_input)
        layout.addLayout(self._build_strength_bar())

        layout.addWidget(self._caption("Confirm new password"))
        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input.setMinimumHeight(theme.FIELD_HEIGHT)
        self.confirm_password_input.returnPressed.connect(self._on_change_password)
        layout.addWidget(self.confirm_password_input)

        self.password_status = self._status_label()
        layout.addWidget(self.password_status)

        self.change_password_button = QPushButton("Change Password")
        self.change_password_button.setObjectName("PrimaryButton")
        self.change_password_button.setMinimumHeight(54)
        self.change_password_button.setStyleSheet("font-size: 16px;")
        self.change_password_button.setCursor(Qt.PointingHandCursor)
        self.change_password_button.clicked.connect(self._on_change_password)
        layout.addWidget(self.change_password_button)
        return card

    def _build_strength_bar(self):
        """Three-segment strength hint: >= 4 weak, >= 8 good, >= 12 strong."""
        row = QHBoxLayout()
        row.setSpacing(theme.SP_1)

        self.strength_segments = []
        for _ in range(3):
            segment = QFrame()
            segment.setObjectName("StrengthSegment")
            segment.setProperty("level", "off")
            segment.setFixedHeight(8)
            row.addWidget(segment, 1)
            self.strength_segments.append(segment)

        self.strength_label = QLabel("")
        self.strength_label.setObjectName("MutedLabel")
        self.strength_label.setMinimumWidth(48)
        row.addWidget(self.strength_label)
        return row

    def _update_strength(self, *_args):
        length = len(self.new_password_input.text())
        if length >= 12:
            score, level = 3, "strong"
        elif length >= 8:
            score, level = 2, "good"
        elif length >= MIN_PASSWORD_LENGTH:
            score, level = 1, "weak"
        else:
            score, level = 0, "off"

        for index, segment in enumerate(self.strength_segments):
            segment.setProperty("level", level if index < score else "off")
            theme.repolish(segment)
        self.strength_label.setText(
            {"off": "", "weak": "weak", "good": "good", "strong": "strong"}[level]
        )

    # ------------------------------ appearance ------------------------- #
    def _build_appearance_card(self):
        card, layout = make_card(
            "🎨  Appearance", "The theme applies immediately and is remembered."
        )

        layout.addWidget(self._caption("Theme"))

        control = QFrame()
        control.setObjectName("SegmentedControl")
        control_row = QHBoxLayout(control)
        control_row.setContentsMargins(4, 4, 4, 4)
        control_row.setSpacing(4)

        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)

        self.dark_button = QPushButton("🌙  Dark")
        self.light_button = QPushButton("☀️  Light")
        for button, name in ((self.dark_button, "dark"), (self.light_button, "light")):
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(160)
            button.setMinimumHeight(theme.BUTTON_HEIGHT)
            button.clicked.connect(lambda _checked=False, n=name: self._on_theme(n))
            self.theme_group.addButton(button)
            control_row.addWidget(button)

        wrapper = QHBoxLayout()
        wrapper.addWidget(control, 0)
        wrapper.addStretch(1)
        layout.addLayout(wrapper)

        layout.addSpacing(theme.SP_2)
        layout.addWidget(self._caption("Preview"))
        self.preview_row = QHBoxLayout()
        self.preview_row.setSpacing(theme.SP_3)
        layout.addLayout(self.preview_row)
        self._rebuild_preview()
        return card

    # ------------------------------ AI assistant ----------------------- #
    #: shown in the AI card so everyone can see what leaves this computer
    AI_SENT = ("your question", "the AI's own earlier answers in the same chat",
               "matching passages from your company's documents that you are allowed to read")
    AI_NEVER_SENT = ("your tasks, deadlines and calendar", "work sessions, timers and team numbers",
                     "camera images, screenshots and window titles", "other people's chats")
    AI_PROVIDER_NOTE = (
        "General questions are answered by the openai/gpt-oss-120b model at Groq, through your "
        "company's server. Groq does not keep these requests by default, but may keep logs for a "
        "limited time (up to 30 days) to investigate problems or abuse, under its own terms.")

    def _build_ai_card(self):
        card, layout = make_card(
            "🤖  AI assistant",
            "The AI Chat answers questions about your tasks, calendar and team from your own data. "
            "General questions (for example “how do I build a CNN?”) can be answered by an online AI model.")

        self.ai_model_check = QCheckBox("Use the online AI model for general questions")
        self.ai_model_check.setCursor(Qt.PointingHandCursor)
        self.ai_model_check.toggled.connect(self._on_ai_model_toggled)
        layout.addWidget(self.ai_model_check)

        self.ai_status_label = QLabel("")
        self.ai_status_label.setObjectName("MutedLabel")
        self.ai_status_label.setWordWrap(True)
        layout.addWidget(self.ai_status_label)

        self.ai_privacy_label = QLabel(
            "<b>Sent to the model:</b> " + "; ".join(self.AI_SENT) + ".<br>"
            "<b>Never sent:</b> " + "; ".join(self.AI_NEVER_SENT) + ".<br>" + self.AI_PROVIDER_NOTE)
        self.ai_privacy_label.setObjectName("MutedLabel")
        self.ai_privacy_label.setWordWrap(True)
        self.ai_privacy_label.setTextFormat(Qt.RichText)
        layout.addWidget(self.ai_privacy_label)
        self._refresh_ai_card()
        return card

    def _refresh_ai_card(self):
        forced = preferences.forced_off()
        self.ai_model_check.blockSignals(True)
        self.ai_model_check.setChecked(preferences.use_ai_model() and not forced)
        self.ai_model_check.blockSignals(False)
        self.ai_model_check.setEnabled(not forced)
        from llm.service import ModelService

        _state, text = model_status.snapshot(preferences.model_enabled(), service=ModelService(self.db)
                                             if getattr(self.db, "api", None) is not None else None)
        if forced:
            text += "  (switched off from outside: OFFICE_LLM=0)"
        self.ai_status_label.setText(text)

    def _on_ai_model_toggled(self, checked):
        preferences.set_use_ai_model(checked)
        self._refresh_ai_card()

    # ------------------------------ e-mail ----------------------------- #
    EMAIL_LANGUAGES = (("English", "en"), ("العربية (Arabic)", "ar"))

    def _build_email_card(self):
        card, layout = make_card(
            "✉️  Notifications",
            "E-mails from your company's Office Assistant server to your sign-in address.")
        self.email_meetings_check = QCheckBox("E-mail me about meetings and unread messages")
        self.email_meetings_check.setCursor(Qt.PointingHandCursor)
        self.email_meetings_check.toggled.connect(self._on_email_toggled)
        layout.addWidget(self.email_meetings_check)

        urgent = QLabel("Urgent tasks that a manager gives you are always e-mailed.")
        urgent.setObjectName("MutedLabel")
        urgent.setWordWrap(True)
        layout.addWidget(urgent)

        row = QHBoxLayout()
        row.addWidget(self._caption("E-mail language"))
        self.email_language_combo = QComboBox()
        for label, code in self.EMAIL_LANGUAGES:
            self.email_language_combo.addItem(label, code)
        self.email_language_combo.currentIndexChanged.connect(self._on_email_language)
        row.addWidget(self.email_language_combo)
        row.addStretch(1)
        layout.addLayout(row)

        self.email_status = self._status_label()
        layout.addWidget(self.email_status)
        return card

    def _refresh_email_card(self):
        """Shown only when signed in online (the e-mails come from the server)."""
        prefs = self.db.email_preferences() if self.db is not None else None
        self.email_card.setVisible(prefs is not None)
        if prefs is None:
            return
        for widget in (self.email_meetings_check, self.email_language_combo):
            widget.blockSignals(True)
        self.email_meetings_check.setChecked(prefs["email_notifications"])
        self.email_language_combo.setCurrentIndex(max(self.email_language_combo.findData(prefs["language"]), 0))
        for widget in (self.email_meetings_check, self.email_language_combo):
            widget.blockSignals(False)

    def _save_email(self, **change):
        ok, message = self.db.set_email_preferences(**change)
        self._show_status(self.email_status, message, ok)
        if not ok:
            self._refresh_email_card()              # show what the server really has

    def _on_email_toggled(self, checked):
        self._save_email(email_notifications=checked)

    def _on_email_language(self, _index):
        self._save_email(language=self.email_language_combo.currentData())

    def _swatch(self, colour, caption):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SP_2)

        dot = QFrame()
        dot.setFixedSize(20, 20)
        dot.setStyleSheet(
            "background-color: %s; border: 1px solid %s; border-radius: 10px;"
            % (colour, theme.BORDER)
        )
        row.addWidget(dot)

        label = QLabel(caption)
        label.setObjectName("MutedLabel")
        row.addWidget(label)
        return holder

    def _rebuild_preview(self):
        while self.preview_row.count():
            item = self.preview_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        for colour, caption in (
            (theme.ACCENT, "Accent  %s" % theme.ACCENT),
            (theme.SUCCESS, "Success"),
            (theme.WARNING, "Warning"),
            (theme.DANGER, "Danger"),
        ):
            self.preview_row.addWidget(self._swatch(colour, caption))
        self.preview_row.addStretch(1)

    def _sync_theme_buttons(self):
        light = theme.current_theme() == "light"
        self.light_button.setChecked(light)
        self.dark_button.setChecked(not light)

    def _on_theme(self, name):
        if name != theme.current_theme():
            theme.apply_theme(QApplication.instance(), name)
        self._sync_theme_buttons()
        self._rebuild_preview()
        # Inline-styled bits owned by this page follow the new palette.
        self._update_strength()

    # ------------------------------ about ------------------------------ #
    def _build_about_card(self):
        card, layout = make_card("ℹ️  About")

        name = QLabel(APP_NAME)
        name.setObjectName("H3")
        layout.addWidget(name)

        version = QLabel("Version %s" % APP_VERSION)
        version.setObjectName("BodyLabel")
        layout.addWidget(version)

        online = getattr(self.db, "api", None) is not None
        privacy = QLabel("🔒  Your data is kept in your company's account · camera images never leave this PC"
                         if online else "🔒  All data stored locally on this device")
        privacy.setWordWrap(True)
        privacy.setObjectName("FeedText")
        layout.addWidget(privacy)
        return card

    # ------------------------------------------------------------------ #
    #  Data
    # ------------------------------------------------------------------ #
    def _stored_user(self):
        """The user's row from the database (None without a database)."""
        if self.db is None or self.user.get("id") is None:
            return None
        try:
            return self.db.get_user_by_id(self.user["id"])
        except Exception:
            logger.warning("could not read the user", exc_info=True)
            return None

    @staticmethod
    def _initials(full_name):
        parts = [part for part in str(full_name).split() if part]
        return "".join(part[0].upper() for part in parts[:2]) or "?"

    def refresh(self):
        """Load the profile fields from the database (or the user dict)."""
        self._refresh_ai_card()
        row = self._stored_user() or {}
        full_name = row.get("full_name") or self.user.get("full_name", "")
        username = row.get("username") or self.user.get("username", "")
        role = row.get("role") or self.user.get("role", "employee")

        self.full_name_input.setText(full_name)
        self.username_input.setText(username)
        # online, the e-mail address is the sign-in and is managed by the company
        fixed = not getattr(self.db, "can_change_username", True)
        self.username_input.setReadOnly(fixed)
        self.username_input.setToolTip("Your sign-in e-mail cannot be changed here" if fixed else "")
        self.identity_name.setText(full_name)
        self.avatar.setText(self._initials(full_name))
        self.role_pill.setText("👔  Manager" if role == "manager" else "🧑  Employee")
        self.role_pill.setObjectName("PillAccent" if role == "manager" else "PillMuted")
        theme.repolish(self.role_pill)

        self.profile_status.setVisible(False)
        self.password_status.setVisible(False)
        self._refresh_email_card()
        self.email_status.setVisible(False)
        self._sync_theme_buttons()

    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _on_save_profile(self):
        full_name = self.full_name_input.text().strip()
        username = self.username_input.text().strip()

        if not full_name or not username:
            self._show_status(
                self.profile_status, "Full name and username cannot be empty.", False
            )
            return
        if self.db is None:
            self._show_status(self.profile_status, "Database not available.", False)
            return

        try:
            ok, message = self.db.update_user_profile(
                self.user["id"], full_name=full_name, username=username
            )
        except Exception:
            logger.warning("profile save failed", exc_info=True)
            self._show_status(
                self.profile_status, "Could not save the profile. Please try again.",
                False,
            )
            return

        self._show_status(
            self.profile_status, "Profile saved." if ok else message, ok
        )
        if not ok:
            return

        self.user["full_name"] = full_name
        self.user["username"] = username
        self.identity_name.setText(full_name)
        self.avatar.setText(self._initials(full_name))
        self.profile_updated.emit(full_name, username)

    def _on_change_password(self):
        current = self.current_password_input.text()
        new = self.new_password_input.text()
        confirm = self.confirm_password_input.text()

        if not current or not new or not confirm:
            self._show_status(self.password_status, "Please fill in all fields.", False)
            return
        if self.db is None:
            self._show_status(self.password_status, "Database not available.", False)
            return

        if new != confirm:
            self._show_status(self.password_status, "New passwords do not match.", False)
            return
        if len(new) < MIN_PASSWORD_LENGTH:
            self._show_status(
                self.password_status,
                "Password must be at least %d characters." % MIN_PASSWORD_LENGTH,
                False,
            )
            return

        try:
            # the current password is checked by the database / server, not here
            ok, message = self.db.change_password(self.user["id"], current, new)
        except Exception:
            logger.warning("password save failed", exc_info=True)
            self._show_status(
                self.password_status, "Could not save the password. Please try again.",
                False,
            )
            return

        self._show_status(
            self.password_status, "Password changed." if ok else message, ok
        )
        if ok:
            self.current_password_input.clear()
            self.new_password_input.clear()
            self.confirm_password_input.clear()
