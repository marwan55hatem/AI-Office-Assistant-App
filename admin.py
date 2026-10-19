"""Standalone admin panel for the Desktop AI Office Assistant.

Run with::

    python admin.py

Deliberately independent of the main application: it never imports a screen from
``ui/`` (only the shared design tokens in ``ui.theme``) and it never touches
``main.py``, so the admin tool keeps working even while the UI is being changed.
"""

import os
import sys

from PyQt5.QtWidgets import QApplication

from ui import theme


def main():
    """Start the admin panel."""
    from database.db_manager import DatabaseManager
    from admin_ui.admin_window import AdminWindow
    from admin_ui.login_dialog import AdminLoginDialog

    scale = theme.compute_ui_scale()
    if scale > 1.0 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = str(scale)

    app = QApplication(sys.argv)
    import app_paths
    if os.path.isfile(app_paths.APP_ICON):
        from PyQt5.QtGui import QIcon

        app.setWindowIcon(QIcon(app_paths.APP_ICON))
    theme.apply_theme(app, theme.load_saved_theme(), persist=False)

    db = DatabaseManager()

    dialog = AdminLoginDialog()
    if dialog.exec_() != dialog.Accepted:
        db.close()
        sys.exit(0)

    window = AdminWindow(db=db)
    window.show()
    exit_code = app.exec_()
    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
