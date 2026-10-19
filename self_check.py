"""Build verification: load every AI model the app ships and run it once.

    OfficeAssistant.exe --self-check        (installed / frozen app)
    python main.py --self-check             (from source)

The result goes to the log (``<user data>/logs/app.log``); the exit code is the number of
failed checks, so ``packaging/build.ps1`` can gate a release on it. No window is opened.
"""
import logging
import time

import numpy as np

logger = logging.getLogger("self_check")

SAMPLE_TEXT = (
    "The quarterly report shows that sales increased by twelve percent compared with last year. "
    "The team opened two new offices and hired forty employees. Management expects further growth "
    "next year because of strong demand for the new product line."
)


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


def _chat():
    from llm.model_manager import get_manager
    manager = get_manager()
    device = manager.load()
    reply = "".join(manager.stream([{"role": "user", "content": "Say hello in three words."}], max_new_tokens=16))
    return f"{device}: {reply.strip()}"


def _database():
    from database.db_manager import DatabaseManager, DB_PATH
    DatabaseManager()
    return DB_PATH


# The chat model goes first: it needs MIN_FREE_VRAM_GB free and would fall back to the CPU
# if BART/MarianMT were already on the GPU, hiding a broken CUDA path.
CHECKS = [("database", _database), ("chat model", _chat), ("detector", _detect),
          ("summarizer", _summarize), ("translator", _translate)]


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
    logger.info("SELF-CHECK done: %d of %d failed", failed, len(CHECKS))
    return failed
