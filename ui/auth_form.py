"""Building blocks shared by the login and the sign-up screens (one copy of each)."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ui import icons, theme

AUTH_CARD_WIDTH = 520          # wide enough for the 28 px title on one line
ACCENT_BAR_HEIGHT = 4
TITLE_FONT_SIZE = 28
SUBMIT_BUTTON_HEIGHT = 56      # the big accent button of a form
BODY_SPACING = 10
FOOTER_TEXT = "🔒 All data stored locally on this device"


class LogoTile(QLabel):
    """The accent logo square (the app logo is always the bot icon; ``glyph`` is ignored)."""

    def __init__(self, glyph, size=64):
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)
        self.on_theme_changed()

    def on_theme_changed(self):
        """Redraw in the colours of the current theme."""
        self.setPixmap(icons.tile("bot", self._size, theme.ACCENT, theme.ON_ACCENT))


def build_auth_card(parent, margins):
    """The centred card with its accent bar.  Returns ``(card, body_layout)``.

    ``margins`` is ``(left, top, right, bottom)`` of the padded body.  The accent
    bar is a sibling of the body so that it reaches the card's edges.
    """
    card = QFrame(parent)
    card.setObjectName("Card")
    card.setFixedWidth(AUTH_CARD_WIDTH)
    theme.apply_card_shadow(card)

    shell = QVBoxLayout(card)
    shell.setContentsMargins(0, 0, 0, 0)
    shell.setSpacing(0)

    accent_bar = QFrame()
    accent_bar.setObjectName("AccentBar")
    accent_bar.setFixedHeight(ACCENT_BAR_HEIGHT)
    shell.addWidget(accent_bar)

    body = QWidget()
    shell.addWidget(body)
    layout = QVBoxLayout(body)
    layout.setContentsMargins(*margins)
    layout.setSpacing(BODY_SPACING)
    return card, layout


def add_brand(layout, icon, title, subtitle, wrap_title=False, wrap_subtitle=False):
    """Icon, title and subtitle centred at the top of the card."""
    logo = LogoTile(icon)
    layout.addWidget(logo, 0, Qt.AlignCenter)
    layout.addSpacing(theme.SP_1)

    title_label = QLabel(title)
    title_label.setObjectName("H1")
    title_label.setStyleSheet("font-size: %dpx;" % TITLE_FONT_SIZE)   # H1 itself would wrap and clip
    title_label.setAlignment(Qt.AlignCenter)
    title_label.setWordWrap(wrap_title)
    layout.addWidget(title_label)

    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("LeadLabel")
    subtitle_label.setAlignment(Qt.AlignCenter)
    subtitle_label.setWordWrap(wrap_subtitle)
    layout.addWidget(subtitle_label)


def make_input(placeholder, password=False):
    """A tall single-line field (optionally hiding what is typed)."""
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    field.setMinimumHeight(theme.FIELD_HEIGHT)
    if password:
        field.setEchoMode(QLineEdit.Password)
    return field


def make_error_label():
    """The red message under the form; hidden until there is something to say."""
    label = QLabel("")
    label.setObjectName("ErrorLabel")
    label.setAlignment(Qt.AlignCenter)
    label.setWordWrap(True)
    label.setVisible(False)
    return label


def make_primary_button(text, on_click):
    """The big accent button of a form."""
    button = QPushButton(text)
    button.setObjectName("PrimaryButton")
    button.setMinimumHeight(SUBMIT_BUTTON_HEIGHT)
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(on_click)
    return button


def add_centered_note(layout, text, wrap=False):
    """A small muted line (hint or footer) centred under the form."""
    label = QLabel(text)
    label.setObjectName("MutedLabel")
    label.setAlignment(Qt.AlignCenter)
    label.setWordWrap(wrap)
    layout.addWidget(label)
    return label
