"""Collapsible navigation sidebar shared by the manager and employee shells.

The sidebar owns the navigation for the authenticated screens: it emits
:attr:`Sidebar.navigate` with the item key and the shell swaps its page stack.
Collapsing animates ``minimumWidth``/``maximumWidth`` together so the content
next to it reflows smoothly, and the collapsed state is remembered between runs
with ``QSettings``.
"""

from PyQt5.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSettings,
    Qt,
    pyqtSignal,
)
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui import icons, theme

BRAND_TILE = 34          # the rounded logo square next to the app name
NAV_ICON_SIZE = 20

SETTINGS_ORGANISATION = "DesktopAIOfficeAssistant"
SETTINGS_APPLICATION = "Sidebar"
SETTINGS_KEY = "sidebar/collapsed"

ROLE_LABELS = {"manager": "👔  Manager", "employee": "🧑  Employee"}


class Sidebar(QFrame):
    """Icon + label navigation rail that animates between two widths."""

    EXPANDED_WIDTH = 300
    COLLAPSED_WIDTH = 80
    ANIM_MS = 180

    navigate = pyqtSignal(str)
    logout_requested = pyqtSignal()

    def __init__(self, user, items, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.user = user or {}
        self.full_name = self.user.get("full_name", "User")
        self.role = self.user.get("role", "employee")
        self.items = list(items or [])

        self._buttons = {}
        self._badges = {}          # key -> QLabel count pill
        self._badge_counts = {}
        self._labels = {}          # key -> (icon label, text label, button)
        self._active_key = None
        self._icon_names = {}           # item key -> icon name (see ui/icons.py)
        self._collapsed = False
        self._anim = None

        self._build_ui()
        self.on_theme_changed()          # draw the brand tile and the line icons

        # Restore the remembered state without animating on startup.
        self._collapsed = self._restore_collapsed()
        self._apply_width(self._target_width())
        self._apply_collapsed_visuals()

    # ------------------------------------------------------------------ #
    #  Construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SP_3, theme.SP_3, theme.SP_3, theme.SP_3
        )
        layout.setSpacing(4)

        # --- brand row ------------------------------------------------- #
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(theme.SP_2)

        self.collapse_button = QPushButton("☰")
        self.collapse_button.setObjectName("IconButton")
        self.collapse_button.setCursor(Qt.PointingHandCursor)
        self.collapse_button.setToolTip("Collapse or expand the sidebar")
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        self.collapse_button.setFixedSize(40, 40)
        brand_row.addWidget(self.collapse_button)

        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(BRAND_TILE, BRAND_TILE)
        brand_row.addWidget(self.brand_icon)

        self.brand_label = QLabel("Office Assistant")
        self.brand_label.setObjectName("SidebarBrand")
        brand_row.addWidget(self.brand_label)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)

        layout.addWidget(self._divider())

        # --- nav items -------------------------------------------------- #
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for item in self.items:
            if not item or item[0] == "separator":
                layout.addWidget(self._divider())
                continue
            _kind, key, icon, label = item
            button = self._make_item(key, icon, label)
            layout.addWidget(button)

        layout.addStretch(1)

        # --- bottom block ---------------------------------------------- #
        layout.addWidget(self._divider())

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(theme.SP_2)

        self.avatar = QLabel(self._initials())
        self.avatar.setObjectName("Avatar")
        self.avatar.setFixedSize(44, 44)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setToolTip(self.full_name)
        bottom.addWidget(self.avatar)

        self.bottom_labels = QWidget()
        labels_layout = QVBoxLayout(self.bottom_labels)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(2)

        self.name_label = QLabel(self.full_name)
        self.name_label.setObjectName("SidebarUserName")
        labels_layout.addWidget(self.name_label)

        self.role_pill = QLabel(ROLE_LABELS.get(self.role, "🧑  Employee"))
        self.role_pill.setObjectName(
            "PillAccent" if self.role == "manager" else "PillMuted"
        )
        self.role_pill.setAlignment(Qt.AlignCenter)
        self.role_pill.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        labels_layout.addWidget(self.role_pill)

        bottom.addWidget(self.bottom_labels, 1)
        layout.addLayout(bottom)

        self.logout_button = QPushButton("🚪   Logout")
        self.logout_button.setObjectName("SidebarLogout")
        self.logout_button.setCursor(Qt.PointingHandCursor)
        self.logout_button.setToolTip("Sign out")
        self.logout_button.clicked.connect(lambda: self.logout_requested.emit())
        layout.addWidget(self.logout_button)

        self.logout_icon_button = QPushButton("🚪")
        self.logout_icon_button.setObjectName("IconButton")
        self.logout_icon_button.setCursor(Qt.PointingHandCursor)
        self.logout_icon_button.setToolTip("Sign out")
        self.logout_icon_button.clicked.connect(
            lambda: self.logout_requested.emit()
        )
        self.logout_icon_button.setVisible(False)
        layout.addWidget(self.logout_icon_button, 0, Qt.AlignHCenter)

    def _make_item(self, key, icon, label):
        button = QPushButton()
        button.setObjectName("SidebarItem")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(label)

        row = QHBoxLayout(button)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SP_2)

        icon_label = QLabel(icon)
        icon_label.setObjectName("SidebarItemIcon")
        if key in icons.NAV_ICONS:
            self._icon_names[key] = icons.NAV_ICONS[key]
            icon_label.setText("")
            icon_label.setPixmap(icons.pixmap(self._icon_names[key], NAV_ICON_SIZE, theme.TEXT_MUTED))
        icon_label.setFixedWidth(28)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(icon_label)

        text_label = QLabel(label)
        text_label.setObjectName("SidebarItemText")
        text_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(text_label, 1)

        badge = QLabel("")
        badge.setObjectName("SidebarBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        badge.setVisible(False)
        row.addWidget(badge)
        self._badges[key] = badge

        button.clicked.connect(lambda _checked=False, k=key: self.navigate.emit(k))
        # The labels are child widgets, so the button's own colour does not reach
        # them: mirror the checked state into a property the stylesheet reads.
        button.toggled.connect(
            lambda checked, i=icon_label, t=text_label, k=key: self._on_item_toggled(k, i, t, checked)
        )

        self._group.addButton(button)
        self._buttons[key] = button
        self._labels[key] = (icon_label, text_label, button)
        return button

    def _on_item_toggled(self, key, icon_label, text_label, active):
        self._mark_active(icon_label, text_label, active)
        self._paint_icon(key, active)

    def _paint_icon(self, key, active):
        """Draw the line icon of one item in the colour of its state (muted / accent)."""
        name = self._icon_names.get(key)
        if name:
            colour = theme.ACCENT_TEXT if active else theme.TEXT_MUTED
            self._labels[key][0].setPixmap(icons.pixmap(name, NAV_ICON_SIZE, colour))

    def on_theme_changed(self):
        """Re-colour every icon after a theme switch (called by ``theme.apply_theme``)."""
        self.brand_icon.setPixmap(icons.tile("bot", BRAND_TILE, theme.ACCENT, theme.ON_ACCENT))
        for key in self._icon_names:
            self._paint_icon(key, key == self._active_key)

    @staticmethod
    def _mark_active(icon_label, text_label, active):
        for label in (icon_label, text_label):
            label.setProperty("active", "true" if active else "false")
            theme.repolish(label)

    @staticmethod
    def _divider():
        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        return line

    def _initials(self):
        parts = [part for part in str(self.full_name).split() if part]
        if not parts:
            return "?"
        return "".join(part[0].upper() for part in parts[:2]) or "?"

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #
    def set_active(self, key):
        """Mark one navigation item as the current page."""
        self._active_key = key
        button = self._buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_user(self, full_name):
        """Show a new display name (avatar initials and tooltip follow)."""
        self.full_name = full_name or "User"
        self.user["full_name"] = self.full_name
        self.name_label.setText(self.full_name)
        self.avatar.setText(self._initials())
        self.avatar.setToolTip(self.full_name)

    def set_badge(self, key, count):
        """Show ``count`` as a small accent pill on a nav item (hidden at 0).

        While the sidebar is collapsed there is no room for the pill, so the
        count moves into the item's tooltip instead.
        """
        badge = self._badges.get(key)
        if badge is None:
            return
        count = max(0, int(count or 0))
        self._badge_counts[key] = count
        badge.setText("99+" if count > 99 else str(count))
        self._refresh_badge(key)

    def _refresh_badge(self, key):
        badge = self._badges[key]
        count = self._badge_counts.get(key, 0)
        badge.setVisible(count > 0 and not self._collapsed)
        if self._collapsed and key in self._labels:
            label = self._labels[key][1].text()
            self._buttons[key].setToolTip(
                "%s (%d)" % (label, count) if count else label
            )

    def is_collapsed(self):
        """True while the sidebar shows icons only."""
        return self._collapsed

    def toggle_collapsed(self):
        """Animate between the wide and the icon-only sidebar."""
        self._animate_to(not self._collapsed)

    # ------------------------------------------------------------------ #
    #  Collapse animation
    # ------------------------------------------------------------------ #
    def _target_width(self):
        return self.COLLAPSED_WIDTH if self._collapsed else self.EXPANDED_WIDTH

    def _apply_width(self, width):
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)

    def _animate_to(self, collapsed):
        if collapsed == self._collapsed:
            return

        self._collapsed = collapsed
        self._save_collapsed(collapsed)

        # Hide the text straight away when collapsing; show it once the rail has
        # widened again, so the labels are never clipped mid-animation.
        if collapsed:
            self._apply_collapsed_visuals()

        target = self._target_width()
        group = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            animation = QPropertyAnimation(self, prop, group)
            animation.setDuration(self.ANIM_MS)
            animation.setStartValue(self.width())
            animation.setEndValue(target)
            animation.setEasingCurve(QEasingCurve.InOutQuad)
            group.addAnimation(animation)
        group.finished.connect(self._on_animation_finished)
        self._anim = group
        group.start(QParallelAnimationGroup.DeleteWhenStopped)

    def _on_animation_finished(self):
        self._apply_width(self._target_width())
        self._apply_collapsed_visuals()

    def _apply_collapsed_visuals(self):
        """Show icons only when collapsed, labels + profile when expanded."""
        collapsed = self._collapsed
        self.brand_label.setVisible(not collapsed)
        self.brand_icon.setVisible(not collapsed)
        self.bottom_labels.setVisible(not collapsed)
        self.name_label.setVisible(not collapsed)
        self.logout_button.setVisible(not collapsed)
        self.logout_icon_button.setVisible(collapsed)

        for icon_label, text_label, button in self._labels.values():
            text_label.setVisible(not collapsed)
            # Collapsed: icons only, so the label moves into the tooltip.
            button.setToolTip(text_label.text() if collapsed else "")
            if collapsed:
                button.setFixedWidth(self.COLLAPSED_WIDTH - 2 * theme.SP_3)
            else:
                button.setMinimumWidth(0)
                button.setMaximumWidth(16777215)
            layout = button.layout()
            if layout is not None:
                layout.setContentsMargins(
                    theme.SP_2 if collapsed else 0, 0, 0, 0
                )

        for key in self._badges:
            self._refresh_badge(key)

    # ------------------------------------------------------------------ #
    #  Persistence
    # ------------------------------------------------------------------ #
    @staticmethod
    def _settings():
        return QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)

    def _restore_collapsed(self):
        settings = self._settings()
        value = settings.value(SETTINGS_KEY, settings.value("collapsed", False))
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes")
        return bool(value)

    def _save_collapsed(self, collapsed):
        settings = self._settings()
        settings.setValue(SETTINGS_KEY, bool(collapsed))
        settings.sync()
