"""Background threads for the language model, so the window never freezes.

Rules (same as the rest of the app): the worker gets plain data in and sends
plain text out through signals.  It never touches the database or any widget.
"""

from PyQt5.QtCore import QThread, pyqtSignal

from llm.model_manager import ModelNotAvailable, get_manager


class LoadWorker(QThread):
    """Loads the model.  ``loaded(device)`` or ``failed(message)``."""

    loaded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def run(self):
        try:
            self.loaded.emit(get_manager().load())
        except ModelNotAvailable as error:
            self.failed.emit(str(error))
        except Exception as error:                      # never let a thread die silently
            self.failed.emit("Could not load the model: %s" % error)


class GenerateWorker(QThread):
    """Writes one answer.  ``piece(text)`` while writing, then ``done(stopped)`` or ``failed(msg)``."""

    piece = pyqtSignal(str)
    done = pyqtSignal(bool)
    failed = pyqtSignal(str)

    def __init__(self, messages, parent=None):
        super().__init__(parent)
        self._messages = [dict(m) for m in messages]    # a private copy
        self._stopped = False

    def stop(self):
        """Stop writing (the text so far is kept by the caller)."""
        self._stopped = True
        get_manager().cancel()

    def run(self):
        manager = get_manager()
        try:
            for text in manager.stream(self._messages):
                if self._stopped:
                    break
                self.piece.emit(text)
        except ModelNotAvailable as error:
            self.failed.emit(str(error))
            return
        except Exception as error:
            self.failed.emit("The assistant model failed: %s" % error)
            return
        self.done.emit(self._stopped)
