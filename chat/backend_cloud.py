"""Placeholder for a future cloud backend.

It honours the :class:`~chat.backend_base.ChatBackend` contract the only way an
unfinished backend safely can: it cannot be created.  ``ChatClient`` catches
:class:`~chat.backend_base.BackendUnavailable` and carries on with the local backend.
"""

from chat.backend_base import BackendUnavailable, ChatBackend

_NOT_IMPLEMENTED = "The cloud chat backend is not implemented yet."


class CloudBackend(ChatBackend):
    """Remote answers -- not implemented yet."""

    def __init__(self, base_url: str):
        raise BackendUnavailable("%s (%r)" % (_NOT_IMPLEMENTED, base_url))

    # Never reached (the constructor always raises); present so the contract is complete.
    def list_chats(self):
        """See :class:`ChatBackend` (never reached: the backend cannot be created)."""
        raise BackendUnavailable(_NOT_IMPLEMENTED)

    def new_chat(self):
        """See :class:`ChatBackend` (never reached: the backend cannot be created)."""
        raise BackendUnavailable(_NOT_IMPLEMENTED)

    def delete_chat(self, chat_id):
        """See :class:`ChatBackend` (never reached: the backend cannot be created)."""
        raise BackendUnavailable(_NOT_IMPLEMENTED)

    def rename_chat(self, chat_id, title):
        """See :class:`ChatBackend` (never reached: the backend cannot be created)."""
        raise BackendUnavailable(_NOT_IMPLEMENTED)

    def get_messages(self, chat_id, limit=None):
        """See :class:`ChatBackend` (never reached: the backend cannot be created)."""
        raise BackendUnavailable(_NOT_IMPLEMENTED)

    def send_message(self, chat_id, text):
        """See :class:`ChatBackend` (never reached: the backend cannot be created)."""
        raise BackendUnavailable(_NOT_IMPLEMENTED)

    def stream_reply(self, chat_id, **options):
        """See :class:`ChatBackend` (never reached: the backend cannot be created)."""
        raise BackendUnavailable(_NOT_IMPLEMENTED)

    def save_reply(self, chat_id, text, source=None):
        """See :class:`ChatBackend` (never reached: the backend cannot be created)."""
        raise BackendUnavailable(_NOT_IMPLEMENTED)

    def auto_title(self, chat_id):
        """See :class:`ChatBackend` (never reached: the backend cannot be created)."""
        raise BackendUnavailable(_NOT_IMPLEMENTED)
