"""Keyboard / mouse idleness for the current user.

Uses the Win32 ``GetLastInputInfo`` API -- the same signal Windows itself uses
for screen savers and that productivity tools use to detect "away" time.  Only
the *timestamp* of the last input event is read: no keystroke is inspected, no
mouse position, no window content, nothing is stored.
"""

import ctypes
import platform


class InputMonitor:
    """Reports seconds since the last keyboard/mouse input (Windows)."""

    def __init__(self):
        self.os = platform.system()
        self._last_info = None
        self._LASTINPUTINFO = None
        if self.os == "Windows":
            try:

                class LASTINPUTINFO(ctypes.Structure):
                    """Win32 structure filled in by ``GetLastInputInfo``."""
                    _fields_ = [
                        ("cbSize", ctypes.c_uint),
                        ("dwTime", ctypes.c_uint),
                    ]

                self._LASTINPUTINFO = LASTINPUTINFO
            except Exception:
                self._LASTINPUTINFO = None

    def idle_seconds(self) -> int:
        """Return seconds since last user input. -1 if not available."""
        if self.os != "Windows" or self._LASTINPUTINFO is None:
            return -1
        try:
            info = self._LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(info)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return -1
            millis = ctypes.windll.kernel32.GetTickCount() - info.dwTime
            return max(0, int(millis / 1000))
        except Exception:
            return -1

    def is_idle(self, threshold_seconds: int = 90) -> bool:
        """True if the user has not touched keyboard or mouse recently."""
        seconds = self.idle_seconds()
        if seconds < 0:
            return False  # unknown -> assume active
        return seconds >= threshold_seconds
