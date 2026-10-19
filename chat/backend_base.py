"""The contract every chat backend keeps (local engine today, a cloud service later).

``ChatClient`` and the UI depend only on this interface, so a backend can be swapped
without touching them (Liskov substitution): every backend either implements all of
these methods or refuses to be *created* with :class:`BackendUnavailable` -- there is
no half-working backend whose methods fail later.
"""

from abc import ABC, abstractmethod
from typing import Iterable, List, Optional, Tuple

from chat.models import Chat, Message


class BackendUnavailable(RuntimeError):
    """The backend cannot be used (not implemented, not configured, not reachable)."""


class ChatBackend(ABC):
    """Storage of chats plus the assistant that answers them."""

    @abstractmethod
    def list_chats(self) -> List[Chat]:
        """The user's chats, most recently active first."""

    @abstractmethod
    def new_chat(self) -> Chat:
        """Create an empty chat."""

    @abstractmethod
    def delete_chat(self, chat_id: int) -> Tuple[bool, str]:
        """Delete a chat the user owns; returns ``(ok, message)``."""

    @abstractmethod
    def rename_chat(self, chat_id: int, title: str) -> Tuple[bool, str]:
        """Give a chat a new title; returns ``(ok, message)``."""

    @abstractmethod
    def get_messages(self, chat_id: int, limit: Optional[int] = None) -> List[Message]:
        """Messages of a chat, oldest first (the last ``limit`` if given)."""

    @abstractmethod
    def send_message(self, chat_id: int, text: str) -> Message:
        """Store the user's message."""

    @abstractmethod
    def stream_reply(self, chat_id: int, **options) -> Iterable[str]:
        """Answer the newest message; the result is iterable text with ``.full_text``,
        ``.intent``, ``.kind``, ``.source``, ``.messages``, ``.sources``, ``.fallback_text``."""

    @abstractmethod
    def save_reply(self, chat_id: int, text: str, source: Optional[str] = None) -> Optional[Message]:
        """Store the assistant's (possibly cut-short) reply."""

    @abstractmethod
    def auto_title(self, chat_id: int) -> Optional[str]:
        """Title a fresh chat after its first question; ``None`` if nothing changed."""
