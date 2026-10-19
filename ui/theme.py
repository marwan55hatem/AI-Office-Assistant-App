"""Central design system for the Desktop AI Office Assistant.

Everything visual lives in this module:

* two complete colour palettes (``DARK_PALETTE`` / ``LIGHT_PALETTE``) that share
  one indigo accent, so both themes feel like the same product,
* typography, spacing and radius tokens shared by all screens,
* :func:`build_qss` -- turns a palette into the single application stylesheet,
* :func:`apply_theme` / :func:`load_saved_theme` -- switch the whole application
  between the themes at runtime and remember the choice with ``QSettings``,
* small helpers (:func:`rgba`, :func:`apply_card_shadow`, :func:`repolish`,
  :func:`pill_qss`, :func:`row_button_qss`, :func:`fmt_hms`).

The colour tokens are also exposed as module attributes (``theme.ACCENT``,
``theme.TEXT_MUTED``, ...) and are re-pointed whenever the theme changes, so code
that reads them at call time always sees the active palette.  The older names
(``CARD``, ``CARD_HOVER``, ``ELEVATED``) are kept as aliases.

Qt parses 8-digit hex colours as ``#AARRGGBB`` (alpha first), *not* CSS
``#RRGGBBAA``, so translucent colours are always written with ``rgba()``.
Qt style sheets also do not understand ``letter-spacing`` or ``text-transform``;
those are intentionally not used (they only produce parser warnings).

Nothing in here imports a screen, so the module stays dependency free.
"""

import logging
from string import Template

from PyQt5.QtCore import QPointF, QSettings, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPalette, QPolygonF

logger = logging.getLogger(__name__)

SETTINGS_ORGANISATION = "DesktopAIOfficeAssistant"
SETTINGS_APPLICATION = "UI"
SETTINGS_THEME_KEY = "theme"

# --------------------------------------------------------------------------- #
#  Colour palettes
# --------------------------------------------------------------------------- #
# The palette matches the Figma design file ("Office Assistant - New GUI"): enterprise blue +
# amber highlight.  The ACCENT differs per theme (brighter blue on dark, deep blue on light).
# Old note: ACCENT used to be identical in both themes.  ACCENT_TEXT is the same hue shifted for
# use as *text* (active nav label, links) so it keeps >= 4.5:1 on each surface;
# the *_SOLID tokens are the fills used behind white button text.
DARK_PALETTE = {
    "BACKGROUND": "#0B1220",
    "SURFACE": "#111B2E",
    "SURFACE_HOVER": "#17233B",
    "SURFACE_ELEVATED": "#1C2A47",
    "ALT_ROW": "#0E1729",
    "ACCENT": "#2563EB",
    "ACCENT_HOVER": "#1D4FD0",
    "ACCENT_PRESS": "#1A44B5",
    "ACCENT_TEXT": "#8DB4FF",
    "ACCENT_SOFT": "rgba(59, 130, 246, 46)",
    "SUCCESS": "#2FBF8A",
    "SUCCESS_SOLID": "#15805A",
    "SUCCESS_HOVER": "#11694A",
    "SUCCESS_PRESS": "#0D5A3F",
    "WARNING": "#F59E0B",
    "WARNING_HOVER": "#D98A07",
    "DANGER": "#EF5350",
    "DANGER_SOLID": "#C8433B",
    "DANGER_HOVER": "#B33A33",
    "DANGER_PRESS": "#9C312B",
    "INFO": "#60A5FA",
    "TEXT_PRIMARY": "#E8EEF9",
    "TEXT_SECONDARY": "#AAB6CC",
    "TEXT_MUTED": "#7A8AA6",
    "BORDER": "#26354F",
    "BORDER_SOFT": "#1A2840",
    "ON_ACCENT": "#FFFFFF",
    "CAMERA_BG": "#070C17",
    "CAMERA_TEXT": "#8A9BB8",
    "CAMERA_ACTIVE": "#8A9BB8",
    "SHADOW_ALPHA": 90,
}

LIGHT_PALETTE = {
    "BACKGROUND": "#F3F6FB",
    "SURFACE": "#FFFFFF",
    "SURFACE_HOVER": "#EEF3FB",
    "SURFACE_ELEVATED": "#FFFFFF",
    "ALT_ROW": "#F7F9FD",
    "ACCENT": "#1E40AF",
    "ACCENT_HOVER": "#1A3899",
    "ACCENT_PRESS": "#163084",
    "ACCENT_TEXT": "#1E40AF",
    "ACCENT_SOFT": "rgba(30, 64, 175, 34)",
    "SUCCESS": "#0F7B53",
    "SUCCESS_SOLID": "#0F7B53",
    "SUCCESS_HOVER": "#0C6745",
    "SUCCESS_PRESS": "#095538",
    "WARNING": "#B45309",
    "WARNING_HOVER": "#9A4607",
    "DANGER": "#C62828",
    "DANGER_SOLID": "#C62828",
    "DANGER_HOVER": "#AB2222",
    "DANGER_PRESS": "#901D1D",
    "INFO": "#1D5FB8",
    "TEXT_PRIMARY": "#0F1B33",
    "TEXT_SECONDARY": "#44526B",
    "TEXT_MUTED": "#66758F",
    "BORDER": "#DCE4F0",
    "BORDER_SOFT": "#E8EEF7",
    "ON_ACCENT": "#FFFFFF",
    "CAMERA_BG": "#0B1220",
    "CAMERA_TEXT": "#8A9BB8",
    "CAMERA_ACTIVE": "#8A9BB8",
    "SHADOW_ALPHA": 40,
}

PALETTES = {"dark": DARK_PALETTE, "light": LIGHT_PALETTE}

CURRENT_PALETTE = DARK_PALETTE
CURRENT_THEME = "dark"

# --------------------------------------------------------------------------- #
#  Typography tokens
# --------------------------------------------------------------------------- #
FONT_FAMILY = '"Segoe UI", "Segoe UI Emoji", "Segoe UI Symbol", sans-serif'
H1_SIZE = 32
H2_SIZE = 24
H3_SIZE = 18
BODY_SIZE = 15
BODY_LG_SIZE = 16
SMALL_SIZE = 13
LABEL_SIZE = 13
TABLE_TEXT_SIZE = 15
SECTION_SIZE = 17
TIMER_SIZE = 56
STAT_NUMBER_SIZE = 30
STAT_LABEL_SIZE = 13
BADGE_SIZE = 12
ERROR_SIZE = 13
TOOLTIP_SIZE = 13
ICON_SIZE = 22          # sidebar / toolbar glyphs (inline icons are never < 14)

# Legacy aliases (the screens and older styles refer to these names).
BASE_FONT_SIZE = BODY_SIZE
TITLE_SIZE = H1_SIZE

# --------------------------------------------------------------------------- #
#  Spacing / radius tokens
# --------------------------------------------------------------------------- #
SP_1 = 6
SP_2 = 10
SP_3 = 14
SP_4 = 20
SP_5 = 24
SP_6 = 28
SP_8 = 40
SP_10 = 52

R_SM = 8
R_MD = 12
R_LG = 16
R_PILL = 999

CARD_PADDING = SP_5
CONTENT_MARGIN = SP_6
NAVBAR_HEIGHT = 76
INPUT_HEIGHT = 48
BUTTON_HEIGHT = 50
FIELD_HEIGHT = 52          # the taller single-line fields of forms (login, settings, dialogs)
BUTTON_PRIMARY_HEIGHT = 54
TABLE_ROW_HEIGHT = 56
TABLE_HEADER_HEIGHT = 52
ROW_BUTTON_HEIGHT = 38


# --------------------------------------------------------------------------- #
#  Colour helpers
# --------------------------------------------------------------------------- #
def rgba(hex_colour, alpha):
    """Return ``rgba(r, g, b, a)`` for ``#RRGGBB`` and an alpha of 0-255.

    An ``alpha`` between 0 and 1 (a float) is read as a fraction.  Qt cannot read
    CSS ``#RRGGBBAA``; this keeps translucent colours defined once from the
    palette tokens.
    """
    value = str(hex_colour).lstrip("#")
    if len(value) == 8:  # already #AARRGGBB from Qt's point of view
        value = value[2:]
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    if isinstance(alpha, float) and 0.0 <= alpha <= 1.0:
        alpha = int(round(alpha * 255))
    return "rgba(%d, %d, %d, %d)" % (red, green, blue, int(alpha))


def pill_qss(colour, alpha=34, border_alpha=90, radius=R_PILL, padding="3px 10px"):
    """Inline stylesheet for a small coloured pill (status badges, tags)."""
    return (
        "background-color: %s;"
        " color: %s;"
        " border: 1px solid %s;"
        " border-radius: %dpx;"
        " padding: %s;"
        " font-size: %dpx;"
        " font-weight: 600;"
        % (rgba(colour, alpha), colour, rgba(colour, border_alpha), radius, padding,
           BADGE_SIZE)
    )


def row_button_qss(danger=False, success=False):
    """Compact inline style for a labelled button inside a table cell.

    The application stylesheet pads buttons for full-width actions, which leaves
    no room for a label in a table row, so row actions carry this style.
    """
    p = CURRENT_PALETTE
    if danger or success:
        fill, hover, press = (
            (p["DANGER_SOLID"], p["DANGER_HOVER"], p["DANGER_PRESS"]) if danger
            else (p["SUCCESS_SOLID"], p["SUCCESS_HOVER"], p["SUCCESS_PRESS"])
        )
        return (
            "QPushButton { background-color: %s; color: %s; min-height: 0px;"
            " border: 1px solid transparent; border-radius: %dpx;"
            " padding: 4px 16px; font-size: %dpx; font-weight: 600; }"
            "QPushButton:hover { background-color: %s; }"
            "QPushButton:pressed { background-color: %s; }"
            % (fill, p["ON_ACCENT"], R_SM, SMALL_SIZE + 1, hover, press)
        )
    return (
        "QPushButton { background-color: transparent; color: %s; min-height: 0px;"
        " border: 1px solid %s; border-radius: %dpx;"
        " padding: 4px 12px; font-size: %dpx; font-weight: 600; }"
        "QPushButton:hover { color: %s; border: 1px solid %s;"
        " background-color: %s; }"
        "QPushButton:pressed { background-color: %s; color: %s; }"
        % (p["TEXT_SECONDARY"], p["BORDER"], R_SM, SMALL_SIZE + 1, p["TEXT_PRIMARY"],
           p["ACCENT"], p["SURFACE_HOVER"], p["SURFACE_HOVER"], p["TEXT_PRIMARY"])
    )


# --------------------------------------------------------------------------- #
#  Combo-box caret
# --------------------------------------------------------------------------- #
# Qt's stylesheet engine cannot draw a CSS triangle (borders are painted as
# straight bars), so the little caret is rendered once per colour into a PNG in
# the temp directory and referenced from the stylesheet.  QImage/QPainter work
# before a QApplication exists, so this can run at import time.  If anything
# goes wrong the rule degrades to the style's default arrow.
def _caret_down_rule(colour):
    """Return the ``image:`` value for the QComboBox caret sub-control."""
    import os
    import tempfile

    file_name = "dsh_caret_down_%s_24x16.png" % colour.lstrip("#")
    path = os.path.join(tempfile.gettempdir(), file_name)

    try:
        if not os.path.exists(path):
            image = QImage(24, 16, QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setBrush(QColor(colour))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(
                QPolygonF([QPointF(4, 6), QPointF(20, 6), QPointF(12, 12)])
            )
            painter.end()
            if not image.save(path):
                return "none"
        return "url(%s)" % path.replace("\\", "/")
    except Exception:  # pragma: no cover - fall back to the default arrow
        return "none"


# --------------------------------------------------------------------------- #
#  Global stylesheet
# --------------------------------------------------------------------------- #
_QSS_TEMPLATE = Template(
    """
/* ===================== base ===================== */
* {
    outline: none;
}

QWidget {
    background-color: transparent;
    color: ${TEXT_PRIMARY};
    font-family: ${FONT_FAMILY};
    font-size: ${BODY_SIZE}px;
}

QMainWindow, QDialog, QStackedWidget, QMessageBox {
    background-color: ${BACKGROUND};
}

QScrollArea, QAbstractScrollArea {
    background-color: ${BACKGROUND};
    border: none;
}

QScrollArea > QWidget > QWidget,
QWidget#ScrollContent,
QWidget#TabPage {
    background-color: transparent;
}

QFrame#Card QScrollArea {
    background-color: transparent;
}

QSplitter::handle {
    background-color: ${BORDER_SOFT};
}

/* ===================== typography ===================== */
QLabel {
    background-color: transparent;
}

QLabel#H1, QLabel#Title {
    font-size: ${H1_SIZE}px;
    font-weight: 700;
    color: ${TEXT_PRIMARY};
}

QLabel#H2 {
    font-size: ${H2_SIZE}px;
    font-weight: 600;
    color: ${TEXT_PRIMARY};
}

QLabel#H3, QLabel#ScreenTitle, QLabel#CardTitle, QLabel#BrandLabel {
    font-size: ${H3_SIZE}px;
    font-weight: 600;
    color: ${TEXT_PRIMARY};
}

QLabel#LeadLabel {
    font-size: ${BODY_LG_SIZE}px;
    color: ${TEXT_SECONDARY};
}

QLabel#FieldLabel {
    font-size: ${BODY_SIZE}px;
    font-weight: 500;
    color: ${TEXT_SECONDARY};
}

QLabel#BodyLabel {
    font-size: ${TABLE_TEXT_SIZE}px;
    color: ${TEXT_SECONDARY};
}

QLabel#FeedText {
    font-size: 14px;
    color: ${TEXT_SECONDARY};
}

QLabel#AlertText {
    font-size: ${BODY_SIZE}px;
    color: ${TEXT_SECONDARY};
}

QLabel#AppTitle {
    font-size: ${BODY_SIZE}px;
    font-weight: 500;
    color: ${TEXT_PRIMARY};
}

QLabel#SidebarUserName {
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
    color: ${TEXT_PRIMARY};
}

QLabel#Subtitle {
    font-size: ${BODY_SIZE}px;
    color: ${TEXT_MUTED};
}

QLabel#SecondaryLabel {
    font-size: ${SMALL_SIZE}px;
    color: ${TEXT_SECONDARY};
}

QLabel#MutedLabel {
    font-size: ${SMALL_SIZE}px;
    color: ${TEXT_MUTED};
}

QLabel#ErrorLabel {
    font-size: ${ERROR_SIZE}px;
    color: ${DANGER};
}

QLabel#SuccessLabel {
    font-size: ${ERROR_SIZE}px;
    color: ${SUCCESS};
}

QLabel#DialogTitle {
    font-size: ${H2_SIZE}px;
    font-weight: 600;
    color: ${TEXT_PRIMARY};
}

QLabel#Logo {
    font-size: 64px;
    color: ${TEXT_PRIMARY};
}

QLabel#SectionHeader {
    font-size: ${SECTION_SIZE}px;
    font-weight: 600;
    color: ${ACCENT_TEXT};
    border-bottom: 1px solid ${BORDER_SOFT};
    padding-bottom: ${SP_2}px;
}

QLabel#SectionHeaderSmall {
    font-size: ${BADGE_SIZE}px;
    font-weight: 600;
    color: ${TEXT_MUTED};
    border-bottom: 1px solid ${BORDER_SOFT};
    padding-bottom: ${SP_2}px;
}

QLabel#SectionHeaderAlt {
    font-size: ${SECTION_SIZE}px;
    font-weight: 600;
    color: ${TEXT_PRIMARY};
    border-bottom: 1px solid ${BORDER_SOFT};
    padding-bottom: ${SP_2}px;
}

QLabel#TimerDisplay {
    font-size: ${TIMER_SIZE}px;
    font-weight: 700;
    color: ${TEXT_PRIMARY};
}

QLabel#StatNumber {
    font-size: ${STAT_NUMBER_SIZE}px;
    font-weight: 700;
    color: ${TEXT_PRIMARY};
}

QLabel#StatLabel {
    font-size: ${STAT_LABEL_SIZE}px;
    color: ${TEXT_MUTED};
}

QLabel#CameraPlaceholder {
    color: ${CAMERA_TEXT};
    font-size: 17px;
}

QLabel#CameraActive {
    color: ${CAMERA_ACTIVE};
    font-size: 17px;
}

QLabel#TaskTitle {
    font-size: ${BODY_SIZE}px;
    color: ${TEXT_PRIMARY};
}

QLabel#TaskTitle[done="true"] {
    color: ${TEXT_MUTED};
    text-decoration: line-through;
}

QLabel#EmptyLabel {
    color: ${TEXT_MUTED};
    font-size: ${BODY_SIZE}px;
    padding: ${SP_2}px 2px;
}

QLabel#EmptyIcon {
    font-size: 64px;
}

QLabel#CharCount {
    color: ${TEXT_MUTED};
    font-size: ${SMALL_SIZE}px;
}

QLabel#CharCount[over="true"] {
    color: ${DANGER};
}

QLabel#Avatar {
    background-color: ${ACCENT_SOFT};
    color: ${ACCENT_TEXT};
    border: 1px solid ${ACCENT_BORDER_RGBA};
    border-radius: 22px;
    font-size: 16px;
    font-weight: 700;
}

QLabel#AvatarLarge {
    background-color: ${ACCENT_SOFT};
    color: ${ACCENT_TEXT};
    border: 1px solid ${ACCENT_BORDER_RGBA};
    border-radius: 32px;
    font-size: ${H2_SIZE}px;
    font-weight: 700;
}

QLabel#Dot {
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}

/* ===================== pills / badges ===================== */
QLabel#PillBadge, QLabel#PillAccent {
    background-color: ${ACCENT_SOFT};
    color: ${ACCENT_TEXT};
    border: 1px solid ${ACCENT_BORDER_RGBA};
    border-radius: 13px;
    padding: 4px 12px;
    font-size: ${BADGE_SIZE}px;
    font-weight: 600;
}

QLabel#PillUrgent, QLabel#PillAbsent {
    background-color: ${DANGER_SOFT_RGBA};
    color: ${DANGER};
    border: 1px solid ${DANGER_BORDER_RGBA};
    border-radius: 11px;
    padding: 5px 14px;
    font-size: ${SMALL_SIZE}px;
    font-weight: 600;
}

QLabel#PillDone, QLabel#PillPresent {
    background-color: ${SUCCESS_SOFT_RGBA};
    color: ${SUCCESS};
    border: 1px solid ${SUCCESS_BORDER_RGBA};
    border-radius: 11px;
    padding: 5px 14px;
    font-size: ${SMALL_SIZE}px;
    font-weight: 600;
}

QLabel#PillDistracted {
    background-color: ${WARNING_SOFT_RGBA};
    color: ${WARNING};
    border: 1px solid ${WARNING_BORDER_RGBA};
    border-radius: 11px;
    padding: 5px 14px;
    font-size: ${SMALL_SIZE}px;
    font-weight: 600;
}

QLabel#PillMuted {
    background-color: ${MUTED_SOFT_RGBA};
    color: ${TEXT_MUTED};
    border: 1px solid ${BORDER};
    border-radius: 11px;
    padding: 5px 14px;
    font-size: ${SMALL_SIZE}px;
    font-weight: 600;
}

QLabel#BadgeSuccess {
    background-color: ${SUCCESS_SOFT_RGBA};
    color: ${SUCCESS};
    border: 1px solid ${SUCCESS_BORDER_RGBA};
    border-radius: 17px;
    padding: 8px 14px;
    font-size: ${SMALL_SIZE}px;
    font-weight: 600;
}

QLabel#BadgeMuted {
    background-color: ${MUTED_SOFT_RGBA};
    color: ${TEXT_MUTED};
    border: 1px solid ${BORDER};
    border-radius: 17px;
    padding: 8px 14px;
    font-size: ${SMALL_SIZE}px;
    font-weight: 600;
}

/* ===================== buttons ===================== */
QPushButton {
    background-color: ${ACCENT};
    color: ${ON_ACCENT};
    border: 1px solid transparent;
    border-radius: ${R_MD}px;
    min-height: ${BUTTON_HEIGHT}px;
    padding: 10px 22px;
    font-family: ${FONT_FAMILY};
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: ${ACCENT_HOVER};
}

QPushButton:pressed {
    background-color: ${ACCENT_PRESS};
}

QPushButton:focus {
    border: 1px solid ${ACCENT_TEXT};
}

QPushButton:disabled {
    background-color: ${SURFACE_HOVER};
    color: ${TEXT_MUTED};
    border: 1px solid ${BORDER};
}

QPushButton#PrimaryButton {
    background-color: ${ACCENT};
    color: ${ON_ACCENT};
    min-height: ${BUTTON_PRIMARY_HEIGHT}px;
}

QPushButton#PrimaryButton:hover {
    background-color: ${ACCENT_HOVER};
}

QPushButton#PrimaryButton:pressed {
    background-color: ${ACCENT_PRESS};
}

QPushButton#PrimaryButton:disabled {
    background-color: ${SURFACE_HOVER};
    color: ${TEXT_MUTED};
}

QPushButton#SecondaryButton {
    background-color: ${SURFACE};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
}

QPushButton#SecondaryButton:hover {
    background-color: ${SURFACE_HOVER};
    border: 1px solid ${ACCENT};
}

QPushButton#SecondaryButton:pressed {
    background-color: ${SURFACE_ELEVATED};
}

QPushButton#GhostButton {
    background-color: transparent;
    color: ${TEXT_MUTED};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    min-height: 44px;
    padding: 8px 18px;
    font-size: 14px;
    font-weight: 600;
}

QPushButton#GhostButton:hover {
    background-color: transparent;
    color: ${TEXT_PRIMARY};
    border: 1px solid ${ACCENT};
}

QPushButton#GhostButton:pressed {
    background-color: ${SURFACE_HOVER};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${ACCENT_PRESS};
}

QPushButton#DangerButton {
    background-color: ${DANGER_SOLID};
    color: ${ON_ACCENT};
    border: 1px solid transparent;
}

QPushButton#DangerButton:hover {
    background-color: ${DANGER_HOVER};
}

QPushButton#DangerButton:pressed {
    background-color: ${DANGER_PRESS};
}

QPushButton#DangerButton:disabled {
    background-color: ${SURFACE_HOVER};
    color: ${TEXT_MUTED};
    border: 1px solid ${BORDER};
}

QPushButton#SuccessButton {
    background-color: ${SUCCESS_SOLID};
    color: ${ON_ACCENT};
    border: 1px solid transparent;
}

QPushButton#SuccessButton:hover {
    background-color: ${SUCCESS_HOVER};
}

QPushButton#SuccessButton:pressed {
    background-color: ${SUCCESS_PRESS};
}

QPushButton#IconButton {
    background-color: transparent;
    color: ${TEXT_MUTED};
    border: 1px solid transparent;
    border-radius: ${R_SM}px;
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    padding: 0px;
    font-size: 18px;
}

QPushButton#IconButton:hover {
    background-color: ${SURFACE_HOVER};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
}

QPushButton#IconButton:pressed {
    background-color: ${SURFACE_ELEVATED};
}

QPushButton#NavButton {
    background-color: ${SURFACE};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
    border-left: 3px solid transparent;
    border-radius: ${R_MD}px;
    min-height: 52px;
    padding: 0px 22px;
    text-align: left;
    font-weight: 600;
}

QPushButton#NavButton:hover {
    background-color: ${SURFACE_HOVER};
    border: 1px solid ${BORDER};
    border-left: 3px solid ${ACCENT};
}

QPushButton#NavButton:pressed {
    background-color: ${SURFACE_ELEVATED};
    border-left: 3px solid ${ACCENT};
}

QPushButton#NavTile {
    background-color: ${SURFACE};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    min-height: 56px;
    padding: 4px 20px;
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
    text-align: center;
}

QPushButton#NavTile:hover {
    background-color: ${SURFACE_HOVER};
    border: 1px solid ${ACCENT};
    color: ${TEXT_PRIMARY};
}

QPushButton#NavTile:pressed {
    background-color: ${SURFACE_ELEVATED};
    border: 1px solid ${ACCENT_PRESS};
}

QPushButton#RoleButton {
    background-color: ${SURFACE};
    color: ${TEXT_MUTED};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    min-height: 52px;
    padding: 0px 14px;
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
}

QPushButton#RoleButton:hover {
    background-color: ${SURFACE_HOVER};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${ACCENT};
}

QPushButton#RoleButton:checked {
    background-color: ${ACCENT};
    color: ${ON_ACCENT};
    border: 1px solid ${ACCENT};
}

QPushButton#RoleButton:checked:hover {
    background-color: ${ACCENT_HOVER};
    border: 1px solid ${ACCENT_HOVER};
}

QPushButton#SegmentButton {
    background-color: transparent;
    color: ${TEXT_MUTED};
    border: 1px solid transparent;
    border-radius: 23px;
    min-height: 46px;
    padding: 0px 26px;
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
}

QPushButton#SegmentButton:hover {
    color: ${TEXT_PRIMARY};
    background-color: ${SURFACE_HOVER};
}

QPushButton#SegmentButton:checked {
    background-color: ${ACCENT};
    color: ${ON_ACCENT};
    border: 1px solid ${ACCENT};
}

QPushButton#LinkButton {
    background-color: transparent;
    color: ${TEXT_MUTED};
    border: none;
    min-height: 32px;
    padding: 2px 6px;
    font-size: 14px;
    font-weight: 600;
    text-decoration: underline;
}

QPushButton#LinkButton:hover {
    color: ${ACCENT_TEXT};
    background-color: transparent;
}

/* ===================== text inputs ===================== */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: ${SURFACE};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    padding: 12px 16px;
    min-height: 24px;
    font-size: ${BODY_SIZE}px;
    selection-background-color: ${ACCENT};
    selection-color: ${ON_ACCENT};
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid ${ACCENT};
    background-color: ${SURFACE_HOVER};
}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {
    border: 1px solid ${TEXT_MUTED};
}

QLineEdit:focus:hover, QTextEdit:focus:hover, QPlainTextEdit:focus:hover {
    border: 1px solid ${ACCENT};
}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {
    color: ${TEXT_MUTED};
    background-color: ${BACKGROUND};
}

/* ===================== combo box ===================== */
QComboBox {
    background-color: ${SURFACE};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    padding: 8px 16px;
    min-height: 44px;
    font-size: ${BODY_SIZE}px;
}

QComboBox:hover {
    border: 1px solid ${ACCENT};
}

QComboBox:focus {
    border: 1px solid ${ACCENT};
    background-color: ${SURFACE_HOVER};
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 28px;
    border: none;
    background-color: transparent;
}

QComboBox::down-arrow {
    image: ${CARET_DOWN};
    width: 12px;
    height: 8px;
    margin-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: ${SURFACE_ELEVATED};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    padding: ${SP_1}px;
    selection-background-color: ${ACCENT};
    selection-color: ${ON_ACCENT};
    outline: none;
}

/* ===================== date / time edits ===================== */
QAbstractSpinBox {
    background-color: ${SURFACE};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    padding: 8px 14px;
    min-height: 28px;
    font-size: ${BODY_SIZE}px;
    selection-background-color: ${ACCENT};
    selection-color: ${ON_ACCENT};
}

QAbstractSpinBox:hover {
    border: 1px solid ${ACCENT};
}

QAbstractSpinBox:focus {
    border: 1px solid ${ACCENT};
    background-color: ${SURFACE_HOVER};
}

QAbstractSpinBox:disabled {
    color: ${TEXT_MUTED};
    background-color: ${BACKGROUND};
    border: 1px solid ${BORDER};
}

QTimeEdit::up-button, QTimeEdit::down-button {
    width: 0px;
    border: none;
}

QDateEdit::up-button, QDateEdit::down-button {
    width: 0px;
    border: none;
}

QDateEdit::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 28px;
    border: none;
    background-color: transparent;
}

QDateEdit::down-arrow {
    image: ${CARET_DOWN};
    width: 12px;
    height: 8px;
    margin-right: 8px;
}

/* ===================== calendar widget ===================== */
QCalendarWidget QWidget {
    alternate-background-color: ${SURFACE_HOVER};
}

QCalendarWidget QAbstractItemView:enabled {
    background-color: ${SURFACE};
    color: ${TEXT_PRIMARY};
    selection-background-color: ${ACCENT};
    selection-color: ${ON_ACCENT};
    font-size: ${BODY_SIZE}px;
    outline: 0px;
    border: none;
}

QCalendarWidget QAbstractItemView:disabled {
    color: ${TEXT_MUTED};
}

QCalendarWidget #qt_calendar_navigationbar {
    background-color: ${SURFACE_ELEVATED};
    border-bottom: 1px solid ${BORDER};
}

QCalendarWidget QToolButton {
    color: ${TEXT_PRIMARY};
    background-color: transparent;
    border: none;
    border-radius: ${R_SM}px;
    padding: 6px 12px;
    min-height: 0px;
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
}

QCalendarWidget QToolButton:hover {
    background-color: ${SURFACE_HOVER};
}

QCalendarWidget QToolButton::menu-indicator {
    image: none;
}

QCalendarWidget QMenu {
    background-color: ${SURFACE_ELEVATED};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
}

QCalendarWidget QSpinBox {
    background-color: ${SURFACE};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
    border-radius: ${R_SM}px;
    padding: 2px 8px;
    min-height: 0px;
}

/* ===================== AI chat ===================== */
QFrame#ChatBubbleUser {
    background-color: ${ACCENT_SOFT};
    border: 1px solid ${ACCENT_BORDER_RGBA};
    border-radius: 16px;
    border-bottom-right-radius: 4px;
}

QFrame#ChatBubbleAssistant {
    background-color: ${BACKGROUND};
    border: 1px solid ${BORDER};
    border-radius: 16px;
    border-bottom-left-radius: 4px;
}

QFrame#ChatBubbleUser QLabel, QFrame#ChatBubbleAssistant QLabel {
    background-color: transparent;
}

QLabel#ChatText {
    font-size: ${BODY_SIZE}px;
    color: ${TEXT_PRIMARY};
}

QLabel#ChatText[thinking="true"] {
    color: ${TEXT_MUTED};
    font-style: italic;
}

QFrame#CodeBlock {
    background-color: ${SURFACE};
    border: 1px solid ${BORDER};
    border-radius: ${R_SM}px;
}

QFrame#CodeBlock QLabel#CodeLang {
    font-size: 12px;
    color: ${TEXT_MUTED};
    background-color: transparent;
}

QPushButton#CodeCopyButton {
    background-color: transparent;
    color: ${TEXT_SECONDARY};
    border: 1px solid ${BORDER};
    border-radius: ${R_SM}px;
    min-height: 0px;
    padding: 0px 12px;
    font-size: 12px;
}

QPushButton#CodeCopyButton:hover {
    color: ${TEXT_PRIMARY};
    border: 1px solid ${ACCENT};
}

QPlainTextEdit#CodeText {
    background-color: transparent;
    border: none;
    padding: 0px;
    margin: 0px;
    min-height: 0px;
    color: ${TEXT_PRIMARY};
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
    font-size: 13px;
}

QLabel#ModelBadge {
    font-size: 12px;
    color: ${TEXT_MUTED};
    background-color: transparent;
}

QLabel#ModelBadge[state="ready"] {
    color: ${SUCCESS};
}

QLabel#ModelBadge[state="loading"], QLabel#ModelBadge[state="slow"] {
    color: ${WARNING};
}

QLabel#ChatTime {
    font-size: 11px;
    color: ${TEXT_MUTED};
}

QListWidget#ChatList {
    background-color: transparent;
    border: none;
    outline: none;
}

QListWidget#ChatList::item {
    background-color: ${SURFACE};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    margin: 0px 0px 8px 0px;
}

QListWidget#ChatList::item:hover {
    background-color: ${SURFACE_HOVER};
}

QListWidget#ChatList::item:selected {
    background-color: ${ACCENT_SOFT};
    border: 1px solid ${ACCENT};
}

QLabel#ChatItemTitle {
    font-size: 14px;
    font-weight: 700;
    color: ${TEXT_PRIMARY};
}

QLabel#ChatItemSnippet {
    font-size: 12px;
    color: ${TEXT_MUTED};
}

QLabel#ChatItemTime {
    font-size: 11px;
    color: ${TEXT_MUTED};
}

QMenu {
    background-color: ${SURFACE_ELEVATED};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    padding: 6px;
}

QMenu::item {
    padding: 9px 26px;
    border-radius: ${R_SM}px;
}

QMenu::item:selected {
    background-color: ${ACCENT_SOFT};
}

/* ===================== frames ===================== */
QFrame#Card {
    background-color: ${SURFACE};
    border: 1px solid ${BORDER};
    border-radius: ${R_LG}px;
}

QFrame#Card QLabel, QFrame#CardElevated QLabel, QFrame#StatBox QLabel {
    background-color: transparent;
}

QFrame#CardElevated {
    background-color: ${SURFACE_ELEVATED};
    border: 1px solid ${BORDER};
    border-radius: ${R_LG}px;
}

QFrame#StatBox {
    background-color: ${SURFACE_HOVER};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
}

QFrame#TaskRow {
    background-color: ${SURFACE};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
}

QFrame#EventRow {
    background-color: ${BACKGROUND};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
}

QFrame#EventRow:hover {
    background-color: ${SURFACE_HOVER};
    border: 1px solid ${ACCENT};
}

QFrame#EventRow QLabel {
    background-color: transparent;
}

QFrame#TaskRow:hover {
    background-color: ${SURFACE_HOVER};
    border: 1px solid ${BORDER};
}

QFrame#CameraBox {
    background-color: ${CAMERA_BG};
    border: 1px solid ${BORDER};
    border-radius: ${R_LG}px;
}

QFrame#DropZone {
    background-color: ${SURFACE};
    border: 2px dashed ${BORDER};
    border-radius: ${R_LG}px;
}

QFrame#DropZone:hover {
    background-color: ${SURFACE_HOVER};
    border: 2px dashed ${ACCENT};
}

QFrame#Navbar {
    background-color: ${SURFACE};
    border: none;
    border-bottom: 1px solid ${BORDER};
}

QFrame#Navbar QLabel {
    background-color: transparent;
}

QFrame#Divider, QFrame#HLine {
    background-color: ${BORDER_SOFT};
    border: none;
    max-height: 1px;
    min-height: 1px;
}

QFrame#AccentBar {
    background-color: ${ACCENT};
    border: none;
    border-top-left-radius: ${R_LG}px;
    border-top-right-radius: ${R_LG}px;
    max-height: 4px;
    min-height: 4px;
}

QFrame#SegmentedControl {
    background-color: ${BACKGROUND};
    border: 1px solid ${BORDER};
    border-radius: 29px;
}

QFrame#BarTrack {
    background-color: ${BORDER};
    border: none;
    border-radius: 4px;
    max-height: 8px;
    min-height: 8px;
}

QFrame#BarFill {
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
}

QFrame#StrengthSegment {
    background-color: ${BORDER};
    border: none;
    border-radius: 3px;
}

QFrame#StrengthSegment[level="weak"] {
    background-color: ${DANGER};
}

QFrame#StrengthSegment[level="good"] {
    background-color: ${WARNING};
}

QFrame#StrengthSegment[level="strong"] {
    background-color: ${SUCCESS};
}

QFrame#PillBox {
    background-color: ${SURFACE};
    border: 1px solid ${BORDER};
    border-radius: 20px;
}

/* ===================== sidebar ===================== */
QFrame#Sidebar {
    background-color: ${SURFACE};
    border: none;
    border-right: 1px solid ${BORDER};
}

QFrame#Sidebar QLabel {
    background-color: transparent;
}

QPushButton#SidebarItem {
    background-color: transparent;
    color: ${TEXT_MUTED};
    border: none;
    border-left: 3px solid transparent;
    border-radius: ${R_MD}px;
    min-height: 40px;
    max-height: 40px;
    padding: 0px 12px;
    text-align: left;
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
}

QPushButton#SidebarItem:hover {
    background-color: ${SURFACE_HOVER};
}

QPushButton#SidebarItem:checked {
    background-color: ${ACCENT_SOFT};
    border-left: 3px solid ${ACCENT};
}

QPushButton#SidebarItem:checked:hover {
    background-color: ${ACCENT_SOFT};
}

QLabel#SidebarItemIcon {
    font-size: ${ICON_SIZE}px;
    color: ${TEXT_MUTED};
}

QLabel#SidebarItemText {
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
    color: ${TEXT_MUTED};
}

QLabel#SidebarItemIcon[active="true"] {
    color: ${ACCENT_TEXT};
}

QLabel#SidebarItemText[active="true"] {
    color: ${TEXT_PRIMARY};
}

/* must out-rank 'QFrame#Sidebar QLabel' (transparent background) */
QFrame#Sidebar QLabel#SidebarBadge {
    background-color: ${ACCENT};
    color: ${ON_ACCENT};
    border-radius: 11px;
    min-width: 22px;
    max-width: 40px;
    min-height: 22px;
    max-height: 22px;
    padding: 0px 6px;
    font-size: 12px;
    font-weight: 700;
}

QLabel#SidebarBrand {
    font-size: ${H3_SIZE}px;
    font-weight: 700;
    color: ${TEXT_PRIMARY};
}

QPushButton#SidebarLogout {
    background-color: transparent;
    color: ${TEXT_MUTED};
    border: 1px solid transparent;
    border-radius: ${R_MD}px;
    min-height: 48px;
    padding: 0px 14px;
    text-align: left;
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
}

QPushButton#SidebarLogout:hover {
    background-color: ${DANGER_SOFT_RGBA};
    color: ${DANGER};
    border: 1px solid ${DANGER_BORDER_RGBA};
}

/* ===================== check box ===================== */
QCheckBox {
    background-color: transparent;
    color: ${TEXT_PRIMARY};
    spacing: 10px;
}

QCheckBox::indicator {
    width: 24px;
    height: 24px;
    border-radius: 7px;
    border: 1px solid ${BORDER};
    background-color: ${BACKGROUND};
}

QCheckBox::indicator:hover {
    border: 1px solid ${ACCENT};
}

QCheckBox::indicator:checked {
    background-color: ${SUCCESS_SOLID};
    border: 1px solid ${SUCCESS_SOLID};
}

QCheckBox::indicator:disabled {
    border: 1px solid ${BORDER};
    background-color: ${SURFACE};
}

/* ===================== tables ===================== */
QTableWidget, QTableView {
    font-size: ${TABLE_TEXT_SIZE}px;
    background-color: ${SURFACE};
    alternate-background-color: ${ALT_ROW};
    gridline-color: transparent;
    border: 1px solid ${BORDER};
    border-radius: ${R_LG}px;
    color: ${TEXT_PRIMARY};
    outline: none;
}

QTableWidget::item, QTableView::item {
    padding: 12px 16px;
    border: none;
}

QTableWidget::item:selected, QTableView::item:selected {
    background-color: ${ACCENT_SOFT};
    color: ${TEXT_PRIMARY};
}

QHeaderView {
    background-color: transparent;
    border: none;
}

QHeaderView::section {
    background-color: transparent;
    color: ${TEXT_MUTED};
    font-size: ${BADGE_SIZE}px;
    font-weight: 600;
    padding: 14px 16px;
    border: none;
    border-bottom: 1px solid ${BORDER_SOFT};
}

QTableCornerButton::section {
    background-color: transparent;
    border: none;
}

/* ===================== tabs ===================== */
QTabWidget::pane {
    background-color: ${SURFACE_ELEVATED};
    border: 1px solid ${BORDER};
    border-radius: ${R_MD}px;
    top: 0px;
}

QTabWidget::tab-bar {
    left: 0px;
}

QTabBar {
    background-color: transparent;
    qproperty-drawBase: 0;
}

QTabBar::tab {
    background-color: transparent;
    color: ${TEXT_MUTED};
    border: 1px solid transparent;
    border-radius: 23px;
    padding: 12px 38px 12px 26px;
    margin-right: 6px;
    margin-bottom: 8px;
    font-size: ${BODY_SIZE}px;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    color: ${TEXT_PRIMARY};
    background-color: ${SURFACE_HOVER};
}

QTabBar::tab:selected {
    background-color: ${ACCENT};
    color: ${ON_ACCENT};
}

/* ===================== scroll bars ===================== */
QScrollBar:vertical {
    background-color: ${BACKGROUND};
    width: 12px;
    margin: 0px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: ${BORDER};
    min-height: 30px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background-color: ${ACCENT};
}

QScrollBar:horizontal {
    background-color: ${BACKGROUND};
    height: 12px;
    margin: 0px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: ${BORDER};
    min-width: 30px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background-color: ${ACCENT};
}

QScrollBar::add-line, QScrollBar::sub-line {
    height: 0px;
    width: 0px;
    background-color: transparent;
    border: none;
}

QScrollBar::add-page, QScrollBar::sub-page {
    background-color: transparent;
}

/* ===================== tool tips ===================== */
QToolTip {
    background-color: ${SURFACE_ELEVATED};
    color: ${TEXT_PRIMARY};
    border: 1px solid ${ACCENT};
    border-radius: ${R_SM}px;
    padding: 8px 10px;
    font-size: ${TOOLTIP_SIZE}px;
}
"""
)


def build_qss(palette):
    """Return the full application stylesheet for ``palette``."""
    mapping = {key: str(value) for key, value in palette.items()}
    mapping.update(
        FONT_FAMILY=FONT_FAMILY,
        BODY_SIZE=BODY_SIZE,
        SMALL_SIZE=SMALL_SIZE,
        H1_SIZE=H1_SIZE,
        H2_SIZE=H2_SIZE,
        H3_SIZE=H3_SIZE,
        TIMER_SIZE=TIMER_SIZE,
        STAT_NUMBER_SIZE=STAT_NUMBER_SIZE,
        STAT_LABEL_SIZE=STAT_LABEL_SIZE,
        BADGE_SIZE=BADGE_SIZE,
        ERROR_SIZE=ERROR_SIZE,
        ICON_SIZE=ICON_SIZE,
        BODY_LG_SIZE=BODY_LG_SIZE,
        LABEL_SIZE=LABEL_SIZE,
        TABLE_TEXT_SIZE=TABLE_TEXT_SIZE,
        SECTION_SIZE=SECTION_SIZE,
        TOOLTIP_SIZE=TOOLTIP_SIZE,
        BUTTON_HEIGHT=BUTTON_HEIGHT,
        BUTTON_PRIMARY_HEIGHT=BUTTON_PRIMARY_HEIGHT,
        INPUT_HEIGHT=INPUT_HEIGHT,
        R_SM=R_SM,
        R_MD=R_MD,
        R_LG=R_LG,
        R_PILL=R_PILL,
        SP_1=SP_1,
        SP_2=SP_2,
        SP_4=SP_4,
        CARET_DOWN=_caret_down_rule(palette["TEXT_MUTED"]),
        # Qt needs rgba() rather than #RRGGBBAA for translucent colours.
        ACCENT_BORDER_RGBA=rgba(palette["ACCENT"], 90),
        SUCCESS_SOFT_RGBA=rgba(palette["SUCCESS"], 34),
        SUCCESS_BORDER_RGBA=rgba(palette["SUCCESS"], 90),
        WARNING_SOFT_RGBA=rgba(palette["WARNING"], 34),
        WARNING_BORDER_RGBA=rgba(palette["WARNING"], 90),
        DANGER_SOFT_RGBA=rgba(palette["DANGER"], 34),
        DANGER_BORDER_RGBA=rgba(palette["DANGER"], 90),
        MUTED_SOFT_RGBA=rgba(palette["TEXT_MUTED"], 28),
    )
    return _QSS_TEMPLATE.substitute(mapping)


# --------------------------------------------------------------------------- #
#  Module-level tokens (always point at the active palette)
# --------------------------------------------------------------------------- #
def _sync_module_tokens(palette):
    """Re-point ``theme.ACCENT``, ``theme.TEXT_MUTED``, ... at ``palette``."""
    module = globals()
    for key, value in palette.items():
        module[key] = value
    # Legacy names used by older screens.
    module["CARD"] = palette["SURFACE"]
    module["CARD_HOVER"] = palette["SURFACE_HOVER"]
    module["ELEVATED"] = palette["SURFACE_ELEVATED"]


_sync_module_tokens(DARK_PALETTE)

#: The dark stylesheet, kept under its old name for compatibility.
GLOBAL_QSS = build_qss(DARK_PALETTE)


# --------------------------------------------------------------------------- #
#  Theme switching
# --------------------------------------------------------------------------- #
def current_theme():
    """``"dark"`` or ``"light"`` -- the theme that is currently applied."""
    return CURRENT_THEME


def load_saved_theme():
    """Read the remembered theme name from ``QSettings`` (default ``"dark"``)."""
    try:
        settings = QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)
        value = str(settings.value(SETTINGS_THEME_KEY, "dark")).lower()
    except Exception:
        return "dark"
    return value if value in PALETTES else "dark"


def _save_theme(name):
    try:
        settings = QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)
        settings.setValue(SETTINGS_THEME_KEY, name)
        settings.sync()
    except Exception:
        logger.warning("Could not save the theme choice", exc_info=True)


def apply_app_palette(app, palette=None):
    """Install a base ``QPalette`` matching ``palette`` on ``app``.

    The stylesheet styles the widgets; the palette only covers what Qt paints
    natively (placeholder text, item-view selections, native dialogs) so nothing
    falls back to dark-on-dark or light-on-light.
    """
    palette = palette or CURRENT_PALETTE
    qt_palette = QPalette()
    qt_palette.setColor(QPalette.Window, QColor(palette["BACKGROUND"]))
    qt_palette.setColor(QPalette.WindowText, QColor(palette["TEXT_PRIMARY"]))
    qt_palette.setColor(QPalette.Base, QColor(palette["SURFACE"]))
    qt_palette.setColor(QPalette.AlternateBase, QColor(palette["ALT_ROW"]))
    qt_palette.setColor(QPalette.Text, QColor(palette["TEXT_PRIMARY"]))
    qt_palette.setColor(QPalette.Button, QColor(palette["SURFACE"]))
    qt_palette.setColor(QPalette.ButtonText, QColor(palette["TEXT_PRIMARY"]))
    qt_palette.setColor(QPalette.BrightText, QColor(palette["DANGER"]))
    qt_palette.setColor(QPalette.Highlight, QColor(palette["ACCENT"]))
    qt_palette.setColor(QPalette.HighlightedText, QColor(palette["ON_ACCENT"]))
    qt_palette.setColor(QPalette.ToolTipBase, QColor(palette["SURFACE_ELEVATED"]))
    qt_palette.setColor(QPalette.ToolTipText, QColor(palette["TEXT_PRIMARY"]))
    qt_palette.setColor(QPalette.Link, QColor(palette["ACCENT_TEXT"]))
    if hasattr(QPalette, "PlaceholderText"):
        qt_palette.setColor(QPalette.PlaceholderText, QColor(palette["TEXT_MUTED"]))
    app.setPalette(qt_palette)
    return app


def apply_theme(app, theme_name="dark", persist=True):
    """Apply ``"dark"`` or ``"light"`` to the whole application, live.

    Sets the active palette, installs the stylesheet, re-colours the card
    shadows, repolishes every widget and (unless ``persist`` is False) saves the
    choice under ``QSettings("DesktopAIOfficeAssistant", "UI")["theme"]``.
    """
    global CURRENT_PALETTE, CURRENT_THEME

    name = "light" if str(theme_name).lower() == "light" else "dark"
    CURRENT_THEME = name
    CURRENT_PALETTE = PALETTES[name]
    _sync_module_tokens(CURRENT_PALETTE)

    if app is not None:
        apply_app_palette(app, CURRENT_PALETTE)
        _set_tooltip_font()
        app.setStyleSheet(build_qss(CURRENT_PALETTE))
        _refresh_widgets(app)

    if persist:
        _save_theme(name)
    return name


def _set_tooltip_font():
    """Tool tips take their font from the application, not the stylesheet.

    Without this they render in the platform's tooltip font, which can be larger
    than the app's own text.
    """
    from PyQt5.QtWidgets import QToolTip

    font = QToolTip.font()
    font.setFamily("Segoe UI")
    font.setPixelSize(TOOLTIP_SIZE)
    QToolTip.setFont(font)


def compute_ui_scale():
    """Automatic whole-UI zoom for big screens (1.0 on a 1366x768 laptop).

    Everything -- fonts, icons, fixed-size widgets -- is scaled together through
    Qt's ``QT_SCALE_FACTOR``, so a 1080p screen shows the same layout as a
    1536x864 one, just crisper and larger.  Set ``APP_UI_SCALE`` to override
    (e.g. ``1`` to switch the zoom off).  Must run before ``QApplication``.
    """
    import os

    override = os.environ.get("APP_UI_SCALE")
    if override:
        try:
            return max(0.75, min(float(override), 2.0))
        except ValueError:
            pass
    try:
        import ctypes

        user32 = ctypes.windll.user32
        width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1.0
    return round(max(1.0, min(width / 1536.0, height / 864.0, 1.5)), 2)


def _refresh_widgets(app):
    """Re-colour shadows and re-apply the stylesheet on every live widget."""
    from PyQt5.QtWidgets import QGraphicsDropShadowEffect

    shadow = QColor(0, 0, 0, int(CURRENT_PALETTE["SHADOW_ALPHA"]))
    for widget in app.allWidgets():
        effect = widget.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            effect.setColor(shadow)
        repolish(widget)
        redraw = getattr(widget, "on_theme_changed", None)
        if callable(redraw):
            redraw()                    # widgets that draw pixmaps (icons) re-colour themselves


# --------------------------------------------------------------------------- #
#  Widget helpers
# --------------------------------------------------------------------------- #
def apply_card_shadow(widget):
    """Add a soft drop shadow to a card frame. Call from the screens."""
    from PyQt5.QtWidgets import QGraphicsDropShadowEffect

    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(24)
    effect.setOffset(0, 4)
    effect.setColor(QColor(0, 0, 0, int(CURRENT_PALETTE["SHADOW_ALPHA"])))
    widget.setGraphicsEffect(effect)
    return widget


def repolish(widget):
    """Re-evaluate the stylesheet of ``widget``.

    Needed after changing ``objectName`` or a dynamic property at runtime, since
    Qt does not restyle a widget on its own for those changes.
    """
    if widget is None:
        return
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
    return widget


def fmt_hms(seconds):
    """Format a duration as ``HH : MM : SS`` (the app-wide convention)."""
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return "%02d : %02d : %02d" % (hours, minutes, secs)
