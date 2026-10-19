"""Background active-window + input-idle monitoring thread.

Samples the focused window title every 2 seconds, classifies it, and reports how
long the user has been away from the keyboard and mouse.  Like the camera
thread it only communicates through signals.
"""

import logging
import time

from PyQt5.QtCore import QThread, pyqtSignal

from detection.input_monitor import InputMonitor
from detection.screen_monitor import ScreenMonitor

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL = 2.0  # seconds between samples

# No keyboard/mouse input for this long means the user is away (asleep, in a
# meeting, watching something, ...) even if the camera still sees a face.
IDLE_THRESHOLD_SECONDS = 90


class ScreenThread(QThread):
    """Polls the active window and the user's input idleness."""

    screen_update = pyqtSignal(str, str, int)  # title, category, whatsapp_elapsed
    idle_update = pyqtSignal(bool, int)        # is_idle, idle_seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._input = None
        self._monitor = None

    def run(self):
        self._running = True
        # Kept as an attribute (not a local) so the WhatsApp timer state can be
        # inspected while the session runs.
        self._monitor = ScreenMonitor()
        self._input = InputMonitor()

        while self._running:
            try:
                sample = self._monitor.sample_with_timer()
                self.screen_update.emit(
                    sample["title"],
                    sample["category"],
                    sample.get("whatsapp_elapsed", 0),
                )
            except Exception:
                logger.warning("sample failed", exc_info=True)

            try:
                # One API read per tick; -1 means "unavailable" -> not idle.
                idle_seconds = self._input.idle_seconds()
                is_idle = idle_seconds >= IDLE_THRESHOLD_SECONDS
                self.idle_update.emit(is_idle, idle_seconds)
            except Exception:
                logger.debug("Reading the input idle time failed", exc_info=True)

            # Sleep in small chunks so stop() is responsive.
            for _ in range(20):  # 20 * 0.1s = 2 seconds
                if not self._running:
                    return
                time.sleep(0.1)

    def stop(self):
        """Ask the loop to finish and wait briefly for the thread to end."""
        self._running = False
        if not self.wait(2000):
            logger.warning("stop() timed out waiting for the screen loop to end")
