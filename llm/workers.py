"""Background threads for the online chat model, so the window never freezes.

Rules (same as the rest of the app): the worker gets plain data in and sends plain
text out through signals. It never touches the database or any widget.
"""

from PyQt5.QtCore import QThread, pyqtSignal


class ReadyWorker(QThread):
    """The online model needs no loading: reports ``loaded("cloud")`` at once."""

    loaded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def run(self):
        self.loaded.emit("cloud")


class GenerateWorker(QThread):
    """Streams one answer from the server.

    ``piece(text)`` while writing, then ``done(stopped)`` or ``failed(message)``.
    ``sources`` holds the documents the server used, once the answer is complete.
    ``request`` is ``{"chat_id": ..., "question": ...}``: the server builds the prompt.
    """

    piece = pyqtSignal(str)
    done = pyqtSignal(bool)
    failed = pyqtSignal(str)

    def __init__(self, api, request, parent=None):
        super().__init__(parent)
        self._api = api
        self._request = {"chat_id": str(request["chat_id"]), "question": str(request["question"])}
        self._stopped = False
        self.sources = []

    def stop(self):
        """Stop writing (the text so far is kept by the caller); the connection is closed."""
        self._stopped = True

    def run(self):
        from cloud.api import ApiError, Offline, SessionExpired

        try:
            for event in self._api.stream_events("/ai/chat", self._request, lambda: self._stopped):
                kind = event.get("type")
                if kind == "delta":
                    self.piece.emit(event.get("text", ""))
                elif kind == "done":
                    self.sources = list(event.get("sources") or [])
                elif kind == "error":
                    self.failed.emit(event.get("message") or "The AI model could not answer.")
                    return
        except Offline:
            self.failed.emit("No connection to the server.")
            return
        except SessionExpired:
            self.failed.emit("Your sign-in has ended. Please sign in again.")
            return
        except ApiError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:                      # never let a thread die silently
            self.failed.emit("The AI model failed: %s" % error)
            return
        self.done.emit(self._stopped)
