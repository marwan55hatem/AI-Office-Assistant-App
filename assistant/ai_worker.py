"""Run a slow AI call off the GUI thread.

Generic on purpose: the summarizer uses it today and the translator will reuse
it next.  The callable runs in a QThread and reports back through signals, so no
widget is ever touched from the worker thread.
"""

from PyQt5.QtCore import QThread, pyqtSignal


class AIWorker(QThread):
    """Run ``fn(*args, **kwargs)`` in the background and emit the outcome."""

    finished_ok = pyqtSignal(str)      # result text
    failed = pyqtSignal(str)           # user-facing error message

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished_ok.emit(result if isinstance(result, str) else str(result))
        except Exception as error:
            self.failed.emit(str(error))
