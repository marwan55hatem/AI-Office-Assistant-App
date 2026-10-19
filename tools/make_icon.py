"""Create ``assets/icons/app.ico`` (and ``app.png``) from the logo tile used in the UI.

    python tools/make_icon.py

The logo is the same accent square with the bot icon that the sidebar and the login
screen draw (``ui.icons.tile``), so the window, taskbar and installer icons match the app.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QGuiApplication  # noqa: E402

LOGO_BACKGROUND = "#2563EB"      # theme ACCENT (dark) -- reads well on light and dark taskbars
LOGO_FOREGROUND = "#FFFFFF"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main():
    from PIL import Image

    from ui import icons

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 (needed for QPixmap)
    out_dir = os.path.join(ROOT, "assets", "icons")
    os.makedirs(out_dir, exist_ok=True)
    png = os.path.join(out_dir, "app.png")
    icons.tile("bot", 128, LOGO_BACKGROUND, LOGO_FOREGROUND).toImage().save(png)   # 256 px (2x supersampled)
    image = Image.open(png).convert("RGBA")
    ico = os.path.join(out_dir, "app.ico")
    image.save(ico, sizes=[(s, s) for s in SIZES])
    print("wrote", png, "and", ico)


if __name__ == "__main__":
    main()
