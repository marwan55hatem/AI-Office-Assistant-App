"""YOLO12 person / phone detection.

The model is loaded lazily in :meth:`Detector.__init__` and ``torch`` /
``ultralytics`` are imported there too, so the rest of the application keeps
working on machines where the deep-learning stack is not installed: the camera
thread reports a clear error and the session continues with screen monitoring
only.

The weights live in ``models/yolo12n.pt``; ultralytics downloads them there on
first use when the file is missing.  The class ids below are the COCO ids that
yolo12n was trained on (unchanged from YOLOv8).  To switch models again, change
``YOLO_MODEL_NAME`` only.
"""

import logging
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from app_paths import MODELS_DIR as MODEL_DIR
except ImportError:
    MODEL_DIR = os.path.join(BASE_DIR, "models")
YOLO_MODEL_NAME = "yolo12n.pt"
YOLO_MODEL_PATH = os.path.join(MODEL_DIR, YOLO_MODEL_NAME)
DEFAULT_MODEL = YOLO_MODEL_PATH

logger = logging.getLogger(__name__)

PERSON_CLASS_ID = 0
PHONE_CLASS_ID = 67

INSTALL_HINT = (
    "Install the deep-learning stack with:  "
    "pip install torch torchvision ultralytics"
)


class Detector:
    """Wraps a YOLO model and annotates frames with person/phone boxes."""

    def __init__(self, model_name=DEFAULT_MODEL, device=None):
        # Imported here (not at module import time) so a missing torch/ultralytics
        # cannot break the whole application.
        try:
            import torch
            from ultralytics import YOLO
        except Exception as error:
            raise RuntimeError(
                f"YOLO is unavailable ({type(error).__name__}: {error}). "
                f"{INSTALL_HINT}"
            )

        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = model_name

        model_dir = os.path.dirname(os.path.abspath(model_name))
        if model_dir:
            os.makedirs(model_dir, exist_ok=True)

        try:
            self.model = YOLO(model_name)
        except Exception as error:
            raise RuntimeError(
                f"Could not load the YOLO model '{os.path.basename(model_name)}' "
                f"({type(error).__name__}: {error}). It is downloaded on first "
                f"use, so check the internet connection - or drop a .pt file "
                f"into {MODEL_DIR}."
            )

        # ultralytics exposes .to() on some versions only; inference also gets
        # an explicit device=, so this is best-effort.
        to_device = getattr(self.model, "to", None)
        if callable(to_device):
            try:
                to_device(self.device)
            except Exception:
                logger.warning("Could not move the detector to %s; it stays where it is", self.device, exc_info=True)

        logger.info("YOLO ready on %s (%s)", self.device, os.path.basename(model_name))

    def process_frame(self, frame):
        """Run inference on a BGR numpy frame.

        Returns ``(annotated_frame, person_detected, phone_detected)``.  An
        inference failure degrades to "nothing detected" for that frame instead
        of killing the camera thread.
        """
        try:
            results = self.model(frame, verbose=False, device=self.device)
        except Exception:
            logger.warning("inference failed", exc_info=True)
            return frame, False, False

        person = False
        phone = False

        boxes = getattr(results[0], "boxes", None) if results else None
        if boxes is not None:
            for box in boxes:
                try:
                    class_id = int(box.cls[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                except Exception:
                    logger.debug("Skipping an unreadable detection box", exc_info=True)
                    continue

                if class_id == PERSON_CLASS_ID:
                    person = True
                    self._draw_box(frame, x1, y1, x2, y2, (16, 185, 129), "Person")
                elif class_id == PHONE_CLASS_ID:
                    phone = True
                    self._draw_box(frame, x1, y1, x2, y2, (245, 158, 11), "Phone")

        return frame, person, phone

    @staticmethod
    def _draw_box(frame, x1, y1, x2, y2, color_rgb, label):
        """Draw one labelled rectangle (colours arrive as RGB, OpenCV wants BGR)."""
        import cv2

        color = (color_rgb[2], color_rgb[1], color_rgb[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            frame,
            label,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )
