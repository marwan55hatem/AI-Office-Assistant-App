"""Background camera + YOLO inference thread.

Runs the webcam loop and YOLO inference away from the GUI thread and reports
everything through signals -- it never touches a widget itself.

If the model cannot be loaded (no torch, no internet on the first run) or the
webcam cannot be opened, the thread emits :attr:`error` and finishes; the
application keeps running and the session continues with screen monitoring.
"""

import logging
import time

import cv2
from PyQt5.QtCore import QThread, pyqtSignal

from detection.detector import Detector

logger = logging.getLogger(__name__)

FRAME_DELAY = 0.033  # cap the loop at roughly 30 FPS


class CameraThread(QThread):
    """Live webcam feed with person / phone detection."""

    frame_ready = pyqtSignal(object)          # annotated BGR numpy frame
    detection_update = pyqtSignal(bool, bool)  # person, phone
    error = pyqtSignal(str)

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._running = False
        self.detector = None

    def run(self):
        self._running = True

        try:
            self.detector = Detector()
        except Exception as error:
            self.error.emit(f"Failed to load YOLO: {error}")
            return

        capture = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(self.camera_index)  # fallback backend
        if not capture.isOpened():
            capture.release()
            self.error.emit(
                f"Could not open webcam {self.camera_index}. "
                "Close other apps using it, or check the camera index."
            )
            return

        try:
            while self._running:
                ok, frame = capture.read()
                if not ok:
                    self.error.emit("Frame read failed.")
                    break

                frame = cv2.flip(frame, 1)  # mirror: looks natural in a preview
                annotated, person, phone = self.detector.process_frame(frame)

                self.frame_ready.emit(annotated)
                self.detection_update.emit(person, phone)

                time.sleep(FRAME_DELAY)
        finally:
            capture.release()

    def stop(self):
        """Ask the loop to finish and wait briefly for the thread to end."""
        self._running = False
        if not self.wait(2000):
            # The current inference is taking longer than the grace period; the
            # loop still exits by itself at the next check of _running.
            logger.warning("stop() timed out waiting for the camera loop to end")
