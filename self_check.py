"""Build verification: check that the parts which run on this PC work in this build.

    OfficeAssistant.exe --self-check        (installed / frozen app)
    python main.py --self-check             (from source)

What is checked -- everything that must work without the server:

* **storage**     the user-data folder is writable and the offline queue (outbox) opens there,
* **intent**      the app's own intent classifier (routes AI Chat questions),
* **detector**    YOLO12n person and phone detection,
* **summarizer**  BART summaries,
* **translator**  MarianMT translation.

The company database and the chat model are online since version 2 (the API and Groq), so they
are not part of this check; the app tells the user when the server cannot be reached.

The result goes to the log (``<user data>/logs/app.log``); the exit code is the number of failed
checks, so ``packaging/build.ps1`` can stop a release when one fails. No window is opened.
"""
import logging
import os
import time
import uuid

import numpy as np

logger = logging.getLogger("self_check")

SAMPLE_TEXT = (
    "The quarterly report shows that sales increased by twelve percent compared with last year. "
    "The team opened two new offices and hired forty employees. Management expects further growth "
    "next year because of strong demand for the new product line."
)


def _storage():
    from app_paths import USER_DATA_DIR
    from cloud.outbox import Outbox

    os.makedirs(USER_DATA_DIR, exist_ok=True)
    path = os.path.join(USER_DATA_DIR, f"self-check-{uuid.uuid4().hex[:8]}.db")
    outbox = Outbox(path)
    try:
        return USER_DATA_DIR
    finally:
        outbox.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass


def _intent():
    from assistant.intent_model import get_classifier
    intent, confidence = get_classifier().predict("what are my tasks for today")
    return f"{intent} ({confidence:.2f})"


def _summarize():
    from assistant.summarizer import Summarizer
    return Summarizer().summarize(SAMPLE_TEXT)


def _translate():
    from assistant.translator import Translator
    return Translator("English", "Arabic").translate("The meeting starts at ten.")


def _detect():
    from detection.detector import Detector, DEFAULT_MODEL
    _, person, phone = Detector(DEFAULT_MODEL).process_frame(np.zeros((480, 640, 3), dtype=np.uint8))
    return f"person={person} phone={phone}"


CHECKS = [("storage", _storage), ("intent", _intent), ("detector", _detect), ("summarizer", _summarize),
          ("translator", _translate)]


def run() -> int:
    """Run all checks; return the number that failed."""
    failed = 0
    for name, check in CHECKS:
        started = time.monotonic()
        try:
            result = check()
            logger.info("SELF-CHECK ok   %-10s %5.1fs  %s", name, time.monotonic() - started, str(result)[:120])
        except Exception:
            failed += 1
            logger.exception("SELF-CHECK FAIL %s", name)
    logger.info("SELF-CHECK done: %d of %d passed%s", len(CHECKS) - failed, len(CHECKS),
                "" if not failed else f" ({failed} failed)")
    return failed
