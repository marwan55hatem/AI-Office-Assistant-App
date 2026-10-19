"""Desktop AI Office Assistant -- application entry point.

Run with::

    python main.py

This module is the *composition root*: it creates the shared
:class:`database.db_manager.DatabaseManager`, builds the screens and passes the
database into them.  Logins are verified against ``data/office_assistant.db``.

Threading: widgets and the database are only ever touched from the Qt main
thread.  Slow work (camera + YOLO, window monitoring, summarising, translating,
the language model) runs in ``QThread`` workers that talk to the UI only through
signals -- see ``docs/THREADING.md``.
"""

import logging
import logging.handlers
import sys

# Pre-import sentencepiece BEFORE PyQt5 to avoid a native library crash on
# Windows (confirmed in testing: importing it after Qt aborts the process).
try:
    import sentencepiece  # noqa: F401
except ImportError:
    pass

# Avoid HF Xet backend stalls observed on this network.
import os  # noqa: E402

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import app_paths  # noqa: E402

if app_paths.FROZEN:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")          # the installed app never downloads
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QIcon  # noqa: E402
from PyQt5.QtWidgets import QApplication, QStackedWidget  # noqa: E402

from database.db_manager import DatabaseManager  # noqa: E402
from ui import theme  # noqa: E402
from ui.notifications import TrayNotifier  # noqa: E402
from ui.login_screen import LoginScreen  # noqa: E402
from ui.signup_screen import SignupScreen  # noqa: E402
from ui.employee_screen import EmployeeScreen  # noqa: E402
from ui.todo_screen import TodoScreen  # noqa: E402
from ui.ai_helper_screen import AIHelperScreen  # noqa: E402
from ui.manager_screen import ManagerScreen  # noqa: E402

# Real mode: logins are checked against data/office_assistant.db.
DEMO_MODE = False

WINDOW_SIZE = (1280, 800)
MIN_WINDOW_SIZE = (1100, 700)
#: Shown only before anybody has logged in (and in the database-less demo mode).
PLACEHOLDER_USER = {"id": 2, "full_name": "Marwan Hatem", "role": "employee"}


class App(QStackedWidget):
    """Root window; owns navigation between the screens."""

    def __init__(self, parent=None, db=None):
        """``db`` is the shared database; one is opened at the default path if not given."""
        super().__init__(parent)
        self.setWindowTitle("Desktop AI Office Assistant")
        self.resize(*WINDOW_SIZE)
        self.setMinimumSize(*MIN_WINDOW_SIZE)

        self.db = db if db is not None else DatabaseManager()
        self.current_user = dict(PLACEHOLDER_USER)

        # Tray icon + deadline / event notifications.  It lives as long as the
        # window, but only watches the database while somebody is logged in.
        self.notifier = TrayNotifier(self.db, self)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.notifier.shutdown)

        self.login_screen = self._build_login_screen()
        self.addWidget(self.login_screen)
        self.setCurrentWidget(self.login_screen)

    # ------------------------------------------------------------------ #
    #  Screen factories
    # ------------------------------------------------------------------ #
    def _build_login_screen(self):
        screen = LoginScreen(db=None if DEMO_MODE else self.db)
        screen.login_success.connect(self._on_login)
        # Wired here (not only in __init__) because every navigation back to the
        # login screen builds a fresh instance.
        screen.signup_requested.connect(self._open_signup)
        return screen

    def _build_employee_screen(self):
        screen = EmployeeScreen(user=self.current_user, db=self.db)
        screen.logout_requested.connect(self._logout)
        screen.open_todo.connect(self._open_todo)
        screen.open_ai_helper.connect(self._open_ai_helper)
        return screen

    # ------------------------------------------------------------------ #
    #  Navigation
    # ------------------------------------------------------------------ #
    def _on_login(self, role):
        # LoginScreen authenticated against SQLite and stored the real row in
        # ``logged_in_user``; route with that row so every account (not just the
        # seeded demo ones) sees its own name and id.
        real_user = getattr(self.login_screen, "logged_in_user", None)
        if real_user is not None:
            self.current_user = {
                "id": real_user["id"],
                "full_name": real_user["full_name"],
                "role": real_user["role"],
            }
        else:
            # No database behind the login screen (pure UI demo): keep a safe
            # placeholder so the screens still build.
            self.current_user = dict(PLACEHOLDER_USER)

        if role == "manager":
            screen = ManagerScreen(user=self.current_user, db=self.db)
            screen.logout_requested.connect(self._logout)
        else:
            screen = self._build_employee_screen()

        self._swap(screen)
        self.notifier.start(self.current_user)

    def _open_signup(self):
        screen = SignupScreen(db=self.db)
        screen.go_back.connect(self._show_fresh_login)
        screen.signup_done.connect(self._show_fresh_login)
        self._swap(screen)

    def _show_fresh_login(self):
        """Go back to a clean, fully wired login screen (signup cancelled or finished).

        A new ``LoginScreen`` is built each time because :meth:`_swap` deletes the
        page it navigates away from, so the instance that opened the signup form no
        longer exists.  The fresh form also starts with empty fields, so earlier
        credentials cannot be resubmitted by accident.
        """
        self.login_screen = self._build_login_screen()
        self._swap(self.login_screen)

    def _open_todo(self):
        screen = TodoScreen(user=self.current_user, db=self.db)   # loads its own rows from the database
        screen.go_back.connect(self._back_to_employee)
        self._swap(screen)

    def _open_ai_helper(self):
        screen = AIHelperScreen(user=self.current_user)
        screen.go_back.connect(self._back_to_employee)
        self._swap(screen)

    def _back_to_employee(self):
        self._swap(self._build_employee_screen())

    def _logout(self):
        self.notifier.stop()
        self.current_user = dict(PLACEHOLDER_USER)
        self.login_screen = self._build_login_screen()
        self._swap(self.login_screen)

    def _swap(self, new_widget):
        old = self.currentWidget()
        if old is new_widget:
            return

        self.addWidget(new_widget)
        self.setCurrentWidget(new_widget)

        if old is not None:
            # Stop any running timer before the page goes away.
            stop = getattr(old, "stop_session_if_running", None)
            if callable(stop):
                stop()
            self.removeWidget(old)
            old.deleteLater()


def configure_logging():
    """Log to the console and to ``<user data>/logs/app.log`` (rotated, 3 x 1 MB)."""
    handlers = [logging.StreamHandler()]
    try:
        os.makedirs(app_paths.LOG_DIR, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            os.path.join(app_paths.LOG_DIR, "app.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        pass                            # a read-only location must not stop the app
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                        handlers=handlers)
    for noisy in ("PIL", "matplotlib", "urllib3", "httpx", "httpcore", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main():
    """Start the application: scale, theme, window, event loop."""
    configure_logging()
    if "--self-check" in sys.argv:          # build verification, no window (see self_check.py)
        import self_check
        sys.exit(self_check.run())
    # Big screens get an automatic whole-UI zoom (fonts, icons and fixed-size
    # widgets together); set APP_UI_SCALE=1 to switch it off.
    scale = theme.compute_ui_scale()
    if scale > 1.0 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = str(scale)

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    if os.path.isfile(app_paths.APP_ICON):
        app.setWindowIcon(QIcon(app_paths.APP_ICON))
    app.setApplicationName("Desktop AI Office Assistant")
    app.setApplicationDisplayName("Desktop AI Office Assistant")

    # Dark by default; the Settings screen stores the user's choice in QSettings.
    # apply_theme also installs the base palette for the bits Qt paints natively.
    theme.apply_theme(app, theme.load_saved_theme(), persist=False)

    window = App()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
