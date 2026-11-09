"""Small widget helpers shared by several screens (one copy instead of five)."""

from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout

from ui import theme

CARD_MARGINS = (32, 28, 32, 32)       # left, top, right, bottom padding inside a card


def clear_layout(layout):
    """Remove and delete every widget in ``layout``, including those inside nested layouts
    (the layout itself stays). Without the recursion, widgets of a nested row layout would
    stay behind, still drawn on the parent widget."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
            item.layout().deleteLater()


def make_card(title_text, subtitle=None):
    """A titled, shadowed card.  Returns ``(card, content_layout)``."""
    card = QFrame()
    card.setObjectName("Card")
    theme.apply_card_shadow(card)

    layout = QVBoxLayout(card)
    layout.setContentsMargins(*CARD_MARGINS)
    layout.setSpacing(theme.SP_3)

    title = QLabel(title_text)
    title.setObjectName("H3")
    layout.addWidget(title)

    if subtitle:
        hint = QLabel(subtitle)
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
    return card, layout
