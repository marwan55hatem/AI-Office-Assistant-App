"""Active-window monitoring.

Samples the *title* of the window that currently has focus and classifies it as
productive / neutral / distraction / idle.  This is a privacy-light approach:
the screen contents are never read, no screenshots are taken and no keystrokes
are logged -- only the window title Windows already publishes.
"""

import platform
from datetime import datetime

from detection.categories import SCREEN_DISTRACTION, SCREEN_IDLE, SCREEN_NEUTRAL, SCREEN_PRODUCTIVE
from typing import Any, Dict

# Win32 constants used for a *non-blocking* window-title read.
WM_GETTEXT = 0x000D
SMTO_ABORTIFHUNG = 0x0002
TITLE_READ_TIMEOUT_MS = 200

# WhatsApp is neutral at first (a quick check of a message) and only counts as a
# distraction once it has been in focus continuously for this long.  Matching is
# a plain "whatsapp" substring so it covers WhatsApp Desktop and WhatsApp Web in
# any browser.
WHATSAPP_DISTRACTION_THRESHOLD_SECONDS = 90

_send_message_timeout = None


def _get_send_message_timeout():
    """Lazily resolve ``user32.SendMessageTimeoutW`` with 64-bit-safe types."""
    global _send_message_timeout
    if _send_message_timeout is None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        function = user32.SendMessageTimeoutW
        function.restype = wintypes.LPARAM
        function.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            ctypes.c_void_p,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        _send_message_timeout = function
    return _send_message_timeout

PRODUCTIVE_KEYWORDS = [
    "visual studio code", "vscode", "pycharm", "intellij", "android studio",
    "sublime text", "atom", "notepad++", "vim", "neovim",
    "microsoft word", "word", "excel", "powerpoint", "onenote",
    "google docs", "google sheets", "google slides",
    "libreoffice", "openoffice", "wps office",
    "terminal", "powershell", "cmd.exe", "git bash", "wsl",
    "docker", "postman", "insomnia", "jupyter", "colab",
    "mysql workbench", "pgadmin", "mongodb compass",
    "notion", "obsidian", "evernote", "todoist", "trello",
    "slack", "teams", "zoom", "outlook",
    "meet.google.com", "google meet",
    "figma", "photoshop", "illustrator", "blender",
    "gmail", "linkedin",
    "itunes",
]

DISTRACTION_KEYWORDS = [
    "netflix", "youtube", "twitch", "hulu", "disney+", "prime video",
    "instagram", "facebook", "tiktok", "twitter", "x.com",
    "reddit", "snapchat", "pinterest",
    "steam", "epic games", "valorant", "league of legends",
    "fortnite", "minecraft", "pubg", "cs2", "csgo", "dota",
    "roblox", "genshin", "call of duty",
    "vlc", "mpc-hc", "mpv", "potplayer",
]

NEUTRAL_KEYWORDS = [
    "file explorer", "explorer.exe", "settings", "control panel",
    "task manager", "device manager", "calculator", "snipping tool",
    "discord",
    # Music players are "no signal" rather than work.
    # WhatsApp is NOT listed here: it is handled by the time-based rule below.
    "spotify", "music",
]


class ScreenMonitor:
    """Reports what the user is currently looking at (window title only)."""

    def __init__(self):
        self.os = platform.system()
        self.last_title = ""
        self.last_category = SCREEN_IDLE
        self._last_known_title = ""
        # When WhatsApp came to the foreground (None = not on WhatsApp).
        self._whatsapp_started_at = None

    def get_active_window_title(self) -> str:
        """Return the title of the currently focused window, or ''.

        The title is read with ``SendMessageTimeoutW`` rather than
        ``win32gui.GetWindowText``.  ``GetWindowText`` sends ``WM_GETTEXT`` and
        waits for the owning thread to answer, which blocks *indefinitely* when
        that thread is busy -- including our own GUI thread while it waits for
        this worker to stop (measured: >8s vs 0ms).  When the bounded read times
        out we keep the previous title, so a busy window does not flip the
        classification to 'idle'.
        """
        try:
            if self.os == "Windows":
                # Imported lazily so this module still imports on machines
                # without pywin32 / a non-Windows OS.
                import win32gui

                hwnd = win32gui.GetForegroundWindow()  # never blocks
                if hwnd == 0:
                    return ""
            else:
                return ""  # only Windows is supported for now
        except Exception:
            return ""

        title, ok = self._read_window_text(hwnd)
        if ok:
            self._last_known_title = title
            return title
        return self._last_known_title

    @staticmethod
    def _read_window_text(hwnd):
        """Return ``(title, ok)``; ``ok`` is False when the read gave up."""
        try:
            import ctypes

            send = _get_send_message_timeout()
            buffer = ctypes.create_unicode_buffer(512)
            result = ctypes.c_size_t()
            sent = send(
                hwnd,
                WM_GETTEXT,
                512,
                ctypes.cast(buffer, ctypes.c_void_p),
                SMTO_ABORTIFHUNG,
                TITLE_READ_TIMEOUT_MS,
                ctypes.byref(result),
            )
            if not sent:
                return "", False
            return buffer.value or "", True
        except Exception:
            # ctypes unavailable for some reason: fall back to pywin32, which
            # can block, but keeps the monitor working.
            try:
                import win32gui

                return win32gui.GetWindowText(hwnd) or "", True
            except Exception:
                return "", False

    def classify(self, title: str) -> str:
        """Return 'productive' | 'neutral' | 'distraction' | 'idle'."""
        if not title or not title.strip():
            return SCREEN_IDLE

        lowered = title.lower()
        for keyword in DISTRACTION_KEYWORDS:
            if keyword in lowered:
                return SCREEN_DISTRACTION
        for keyword in PRODUCTIVE_KEYWORDS:
            if keyword in lowered:
                return SCREEN_PRODUCTIVE
        return SCREEN_NEUTRAL      # known-neutral apps and anything unrecognised

    @staticmethod
    def _is_whatsapp(title: str) -> bool:
        """True for WhatsApp Desktop and WhatsApp Web in any browser."""
        return "whatsapp" in (title or "").lower()

    def sample_with_timer(self) -> Dict[str, Any]:
        """Sample the active window, applying the WhatsApp time-based rule.

        WhatsApp is 'neutral' for the first
        :data:`WHATSAPP_DISTRACTION_THRESHOLD_SECONDS` seconds and becomes a
        'distraction' afterwards; focusing anything else resets its timer.

        The returned dict also carries ``whatsapp_elapsed`` (seconds, 0 when the
        window is not WhatsApp) so callers can render a countdown.
        """
        now = datetime.now()
        title = self.get_active_window_title()
        on_whatsapp = self._is_whatsapp(title)

        if not on_whatsapp:
            self._whatsapp_started_at = None
        elif self._whatsapp_started_at is None:
            self._whatsapp_started_at = now

        elapsed = 0
        if on_whatsapp:
            elapsed = int((now - self._whatsapp_started_at).total_seconds())
            category = (
                SCREEN_DISTRACTION
                if elapsed >= WHATSAPP_DISTRACTION_THRESHOLD_SECONDS
                else SCREEN_NEUTRAL
            )
        else:
            category = self.classify(title)

        self.last_title = title
        self.last_category = category
        return {
            "title": title,
            "category": category,
            "timestamp": now,
            "whatsapp_elapsed": elapsed,
        }

    def sample(self) -> Dict[str, Any]:
        """Return dict {title, category, timestamp} (thin wrapper, kept for
        backwards compatibility)."""
        return self.sample_with_timer()
