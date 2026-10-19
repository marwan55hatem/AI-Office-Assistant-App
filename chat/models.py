"""Plain data objects the chat UI works with."""

from dataclasses import dataclass


@dataclass
class Message:
    """One chat message; ``role`` is ``"user"`` or ``"assistant"``."""

    role: str
    content: str
    id: int = 0
    created_at: str = ""
    source: str = ""        # assistant messages: "engine" (database answers) or "llm"


@dataclass
class Chat:
    """One conversation as shown in the chat list."""

    id: int
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0
    last_message: str = ""
