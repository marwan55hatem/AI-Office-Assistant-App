"""The one class the chat UI talks to; it hides which backend is configured."""

import logging
from typing import Iterable, List, Optional, Tuple

from chat import config
from chat.backend_base import BackendUnavailable, ChatBackend
from chat.models import Chat, Message

logger = logging.getLogger(__name__)


class ChatClient:
    """List / create / delete chats, send messages, stream the assistant's reply.

    ``backend`` can be injected (tests, a future cloud backend); by default the one
    named in ``chat/config.py`` is built, falling back to the local backend when the
    configured one is unavailable.
    """

    def __init__(self, db, user_id: int, backend: Optional[ChatBackend] = None):
        self.db = db
        self.user_id = user_id
        self.backend: ChatBackend = backend if backend is not None else self._build_backend()

    def _build_backend(self) -> ChatBackend:
        if config.BACKEND == "cloud":
            try:
                from chat.backend_cloud import CloudBackend

                return CloudBackend(config.CLOUD_URL)
            except BackendUnavailable as problem:
                logger.warning("%s Using the local assistant instead.", problem)
        from chat.backend_local import LocalBackend

        return LocalBackend(self.db, self.user_id)

    def list_chats(self) -> List[Chat]:
        """``[Chat]``, most recently active first."""
        return self.backend.list_chats()

    def new_chat(self) -> Chat:
        """Create an empty chat; returns the :class:`chat.models.Chat`."""
        return self.backend.new_chat()

    def delete_chat(self, chat_id: int) -> Tuple[bool, str]:
        """Delete a chat and its messages. Returns ``(ok, message)``."""
        return self.backend.delete_chat(chat_id)

    def get_messages(self, chat_id: int, limit: Optional[int] = None) -> List[Message]:
        """``[Message]`` of a chat, oldest first (the last ``limit`` if given)."""
        return self.backend.get_messages(chat_id, limit)

    def send_message(self, chat_id: int, text: str) -> Message:
        """Store the user's message; returns it as a ``Message``."""
        return self.backend.send_message(chat_id, text)

    def stream_reply(self, chat_id: int, **options) -> Iterable[str]:
        """Answer the newest message; returns an iterable of text chunks that also
        has ``.full_text`` / ``.intent``.  Call it on the UI thread (it reads the
        database); the returned stream may be iterated in a worker thread."""
        return self.backend.stream_reply(chat_id, **options)

    def save_reply(self, chat_id: int, text: str, source: Optional[str] = None) -> Optional[Message]:
        """Store the assistant's reply (the full text, or what was shown if stopped).
        ``source`` is ``"engine"`` or ``"llm"`` (``ReplyStream.source``)."""
        return self.backend.save_reply(chat_id, text, source)

    def rename_chat(self, chat_id: int, title: str) -> Tuple[bool, str]:
        """Rename a chat. Returns ``(ok, message)``."""
        return self.backend.rename_chat(chat_id, title)

    def auto_title(self, chat_id: int) -> Optional[str]:
        """Name a new chat after its first question; returns the title or None."""
        return self.backend.auto_title(chat_id)
