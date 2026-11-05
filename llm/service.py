"""The language model as the chat screen sees it: a small, replaceable service.

The model now runs online (on the Office Assistant server, which calls Groq); nothing
is loaded on this computer. The screen still needs the same five things -- is it
ready, on what, start "loading", start writing an answer, free it when idle -- so a
fake can stand in for it in tests.
"""

from typing import Optional


class ModelService:
    """The online chat model, reached through the signed-in API client of ``db``."""

    def __init__(self, db=None):
        self.db = db

    @property
    def api(self):
        return getattr(self.db, "api", None)

    def available(self) -> bool:
        """True when questions can be sent: signed in to the server and online."""
        api = self.api
        return api is not None and api.signed_in and api.online

    def is_loaded(self) -> bool:
        return True                      # nothing to load locally

    def device(self) -> Optional[str]:
        return "cloud"

    def create_load_worker(self, parent=None):
        from llm.workers import ReadyWorker

        return ReadyWorker(parent)

    def create_generate_worker(self, request, parent=None):
        """``request`` is ``{"chat_id", "question"}`` (see ``ReplyStream.request``)."""
        from llm.workers import GenerateWorker

        return GenerateWorker(self.api, request, parent)

    def unload_if_idle(self, seconds: Optional[float] = None) -> bool:
        return False                     # nothing is held in memory
