"""Line icons (the same set as the Figma design) drawn from SVG in any colour.

Qt cannot tint an SVG by itself, so the stroke colour is written into the SVG text and
the result is rendered to a high-DPI ``QPixmap``.  The icons are tiny (a few path
commands each), so nothing is cached on disk and a theme switch just re-renders them.
"""

from PyQt5.QtCore import QByteArray, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget

#: Inner SVG (24 x 24 viewBox, stroke icons).  Names follow the Figma file ("icon/<name>").
PATHS = {
    "home": '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
    "calendar": '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "check": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="m9 12 2 2 4-4"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M18 17V9M13 17V5M8 17v-3"/>',
    "bot": '<rect width="18" height="10" x="3" y="11" rx="2"/><circle cx="12" cy="5" r="2"/>'
           '<path d="M12 7v4M8 16h.01M16 16h.01"/>',
    "message": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "book": '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
    "settings": '<circle cx="12" cy="12" r="3"/>'
                '<path d="M12 1v4M12 19v4M4.2 4.2l2.8 2.8M17 17l2.8 2.8M1 12h4M19 12h4M4.2 19.8 7 17M17 7l2.8-2.8"/>',
    "alert": '<path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3z"/><path d="M12 9v4M12 17h.01"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
}

#: Sidebar item key -> icon name (keys of both shells).
NAV_ICONS = {
    "home": "home", "calendar": "calendar", "employees": "users", "sessions": "clock", "session": "clock",
    "tasks": "check", "todo": "check", "reports": "chart", "ai_helper": "bot", "ai_chat": "message",
    "knowledge": "book", "settings": "settings",
}

_SUPERSAMPLE = 2          # render at 2x so the line stays crisp on scaled screens


def _svg(name, color):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
            'stroke="%s" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">%s</svg>'
            % (QColor(color).name(), PATHS[name]))


def pixmap(name, size, color):
    """The icon ``name`` as a ``size`` x ``size`` pixmap in ``color`` (hex string or QColor)."""
    image = QPixmap(size * _SUPERSAMPLE, size * _SUPERSAMPLE)
    image.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, color).encode("utf-8")))
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, size * _SUPERSAMPLE, size * _SUPERSAMPLE))
    painter.end()
    image.setDevicePixelRatio(_SUPERSAMPLE)
    return image


def tile(name, size, background, foreground):
    """A rounded square in ``background`` with the icon in ``foreground`` (the app logo)."""
    from PyQt5.QtGui import QBrush

    image = QPixmap(size * _SUPERSAMPLE, size * _SUPERSAMPLE)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QBrush(QColor(background)))
    painter.setPen(Qt.NoPen)
    radius = size * _SUPERSAMPLE * 0.28
    painter.drawRoundedRect(QRectF(0, 0, size * _SUPERSAMPLE, size * _SUPERSAMPLE), radius, radius)
    inner = size * _SUPERSAMPLE * 0.58
    offset = (size * _SUPERSAMPLE - inner) / 2
    QSvgRenderer(QByteArray(_svg(name, foreground).encode("utf-8"))).render(painter, QRectF(offset, offset, inner, inner))
    painter.end()
    image.setDevicePixelRatio(_SUPERSAMPLE)
    return image


class IconLabel(QWidget):
    """An icon followed by text (a card title).  The icon follows the theme colour."""

    def __init__(self, icon_name, text, object_name="H3", tone="ACCENT_TEXT", size=20, parent=None):
        super().__init__(parent)
        self._name, self._tone, self._size = icon_name, tone, size
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(size, size)
        row.addWidget(self.icon_label)
        self.text_label = QLabel(text)
        self.text_label.setObjectName(object_name)
        row.addWidget(self.text_label)
        row.addStretch(1)
        self.on_theme_changed()

    def on_theme_changed(self):
        """Re-colour the icon (called by ``theme.apply_theme`` on every theme switch)."""
        from ui import theme

        self.icon_label.setPixmap(pixmap(self._name, self._size, getattr(theme, self._tone)))
