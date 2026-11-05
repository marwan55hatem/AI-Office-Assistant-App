"""The strip shown above the pages while the server cannot be reached."""
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel

from ui import theme

OFFLINE_TEXT = (
    "You are offline. Your work session keeps recording and will be sent automatically; "
    "Summarize and Translate still work. Tasks, calendar, chat and reports need a connection."
)


class ConnectionBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConnectionBanner")
        self.setStyleSheet(
            "QFrame#ConnectionBanner { background-color: %s; border: none; }"
            "QFrame#ConnectionBanner QLabel { color: #FFFFFF; font-weight: 600; }" % theme.WARNING)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SP_4, theme.SP_2, theme.SP_4, theme.SP_2)
        self.label = QLabel(OFFLINE_TEXT)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.setVisible(False)

    def set_online(self, online: bool) -> None:
        self.setVisible(not online)
