"""The local backend: SQLite for storage, the assistant engine for the answers.

All database access happens in the thread that calls these methods (the UI
thread).  :meth:`LocalBackend.stream_reply` therefore computes the whole reply
*immediately* and hands back a plain iterator of text pieces; only that iterator
(no database, no engine) may be consumed in a worker thread.
"""

import re
import time

from chat.backend_base import ChatBackend
from chat.models import Chat, Message
from typing import List, Optional

DEFAULT_TITLE = "New Chat"
TITLE_LENGTH = 40


class ReplyStream:
    """A reply that can be shown piece by piece (like typing).

    ``full_text`` is the complete answer, ``intent`` what the question was
    understood as.  Iterating yields word-sized chunks; ``delay`` seconds pass
    between chunks (0 in tests).

    ``kind`` is ``"text"`` (the engine answered from the database; ``full_text`` is
    ready) or ``"llm"`` (the language model must write it: ``messages`` is its
    prompt, to be run by ``llm.workers.GenerateWorker``; ``fallback_text`` is what
    to show if the model cannot answer).  ``source`` is what gets stored with the
    reply: ``"engine"`` or ``"llm"``.
    """

    def __init__(self, text, intent="", confidence=0.0, delay=0.02,
                 kind="text", messages=None, fallback_text="", sources=None):
        self.full_text = text
        self.intent = intent
        self.confidence = confidence
        self.delay = delay
        self.kind = kind
        self.source = "llm" if kind == "llm" else "engine"
        self.messages = messages or []
        self.fallback_text = fallback_text
        self.sources = list(sources or [])      # documents the answer is based on (named after it)

    def __iter__(self):
        for chunk in re.findall(r"\S+\s*|\s+", self.full_text):
            if self.delay:
                time.sleep(self.delay)
            yield chunk


class LocalBackend(ChatBackend):
    """Chat storage + the local assistant engine, for one user."""

    def __init__(self, db, user_id):
        self.db = db
        self.user_id = user_id
        self.chats = db.chats          # only the chat methods of the database
        self.users = db.users
        self._engine = None
        self._kb = None
        self._states = {}          # chat id -> small dict for follow-up questions
        from chat.config import LLM_ENABLED
        self.llm_enabled = LLM_ENABLED

    def _get_engine(self):
        if self._engine is None:
            from assistant.answers import AssistantEngine

            self._engine = AssistantEngine(self.db, self.user_id)
        return self._engine

    # ------------------------------------------------------------------ #
    #  Chats
    # ------------------------------------------------------------------ #
    def list_chats(self) -> List[Chat]:
        """The user's chats, most recently active first."""
        return [
            Chat(id=row["id"], title=row["title"] or DEFAULT_TITLE,
                 created_at=row["created_at"], updated_at=row["updated_at"],
                 message_count=row["message_count"],
                 last_message=row["last_message"] or "")
            for row in self.chats.get_ai_chats(self.user_id)
        ]

    def new_chat(self) -> Chat:
        """Create an empty chat and return it."""
        chat_id = self.chats.create_ai_chat(self.user_id, DEFAULT_TITLE)
        row = self.chats.get_ai_chat(chat_id)
        return Chat(id=chat_id, title=row["title"], created_at=row["created_at"],
                    updated_at=row["updated_at"])

    def delete_chat(self, chat_id: int):
        """Delete a chat (only the owner's chats can be deleted)."""
        self._check_owner(chat_id)
        self._states.pop(chat_id, None)
        return self.chats.delete_ai_chat(chat_id)

    def rename_chat(self, chat_id: int, title: str):
        """Give a chat a new title (blank titles are ignored)."""
        self._check_owner(chat_id)
        title = " ".join(str(title).split())
        if not title:
            return False, "Title cannot be empty"
        return self.chats.update_ai_chat_title(chat_id, title)

    def _check_owner(self, chat_id):
        chat = self.chats.get_ai_chat(chat_id)
        if chat is None or chat["user_id"] != self.user_id:
            raise PermissionError("That chat does not belong to this user")
        return chat

    # ------------------------------------------------------------------ #
    #  Messages
    # ------------------------------------------------------------------ #
    def get_messages(self, chat_id: int, limit: Optional[int] = None) -> List[Message]:
        """Messages of a chat, oldest first."""
        self._check_owner(chat_id)
        return [Message(role=row["role"], content=row["content"], id=row["id"],
                        created_at=row["created_at"], source=row.get("source") or "")
                for row in self.chats.get_ai_messages(chat_id, limit)]

    def send_message(self, chat_id: int, text: str) -> Message:
        """Store the user's message and return it."""
        self._check_owner(chat_id)
        text = str(text).strip()
        if not text:
            raise ValueError("Empty message")
        message_id = self.chats.add_ai_message(chat_id, "user", text)
        return Message(role="user", content=text, id=message_id)

    def stream_reply(self, chat_id, delay=0.02):
        """Answer the newest user message; returns a :class:`ReplyStream`.

        The answer is computed here (database + engine, instantly).  The caller
        shows it chunk by chunk and finally stores it with :meth:`save_reply`.
        """
        self._check_owner(chat_id)
        last = self.chats.get_ai_messages(chat_id, limit=1)
        if not last or last[0]["role"] != "user":
            raise ValueError("There is no user message to answer")
        state = self._states.setdefault(chat_id, {})
        # lets the engine answer "what did I just say?" from this chat's history
        users = [m["content"] for m in self.chats.get_ai_messages(chat_id) if m["role"] == "user"]
        state["previous_user_messages"] = users[:-1]
        question = last[0]["content"]
        reply = self._get_engine().ask(question, state)
        hits = self._documents_for(question, reply)
        wants = self._wants_llm(reply, chat_id, state) or (
            bool(hits) and reply.confidence < self.SURE and reply.intent not in ("greeting", "thanks", "goodbye"))
        if wants and self.llm_ready():
            # Not about the user's own data: the language model answers.  It is given
            # only the fixed instruction, its own earlier answers in this chat, the
            # question and -- if the documents have something -- those passages.  Never
            # tasks, calendar or team data.
            from knowledge.store import format_passages, sources_of
            from llm.prompts import build_messages

            messages = build_messages(self._llm_pairs(chat_id), question, hits)
            return ReplyStream("", "documents" if hits else "general", reply.confidence, delay,
                               kind="llm", messages=messages, sources=sources_of(hits),
                               fallback_text=format_passages(hits) if hits else reply.text)
        if wants and hits:
            from knowledge.store import format_passages

            return ReplyStream(format_passages(hits), "documents", reply.confidence, delay)
        return ReplyStream(reply.text, reply.intent, reply.confidence, delay)

    def _knowledge(self):
        if self._kb is None:
            from knowledge.store import KnowledgeBase

            self._kb = KnowledgeBase(self.db)
        return self._kb

    def _is_manager(self):
        user = self.users.get_user_by_id(self.user_id)
        return bool(user and user.get("role") == "manager")

    def _documents_for(self, question, reply):
        """Passages of the documents this user may see that answer ``question``.

        Only looked up when the engine is not sure the question is about the user's own
        data.  An employee's search never even indexes the manager-only documents.
        """
        if reply.confidence >= self.SURE and reply.intent != "unknown":
            return []
        return self._knowledge().search(question, self._is_manager())

    #: An engine match below this confidence is not trusted to be about the user's data
    #: when the question may just as well be a general one.
    SURE = 0.75
    CERTAIN = 0.9      # above this, even a question with unknown words stays with the engine

    def _wants_llm(self, reply, chat_id, state):
        """Should the language model answer instead of the engine?

        Yes when the engine did not understand ("unknown"), when it only weakly matched
        a manager-only question ("denied" -- e.g. "how do I prevent it?" is not about
        the team), and when the model answered the previous message and the engine is
        unsure about this one (a follow-up like "and what is dropout?").  Clear data
        questions ("Who is the best performer?") always stay with the engine.  The model
        is never given any data, so routing a question to it cannot leak anything.
        """
        if reply.intent == "unknown":
            return True
        if state.get("unfamiliar", 0) >= 1 and reply.confidence < self.CERTAIN:
            return True                  # "What is overfitting?": topic words the engine never saw
        if reply.confidence >= self.SURE:
            return False
        if reply.intent == "denied":
            return True
        if reply.intent in ("greeting", "thanks", "goodbye"):
            return False
        rows = self.chats.get_ai_messages(chat_id, limit=3)
        previous = rows[-2] if len(rows) >= 2 else None
        return bool(previous and previous["role"] == "assistant" and previous.get("source") == "llm")

    def llm_ready(self) -> bool:
        """True when general questions may go to the language model (enabled + files present)."""
        return self.llm_enabled and self._model_present()

    @staticmethod
    def _model_present():
        from llm.model_manager import get_manager

        return get_manager().available()

    def _llm_pairs(self, chat_id):
        """Earlier (question, answer) pairs of this chat that the model itself answered."""
        from chat.config import LLM_HISTORY_PAIRS

        pairs, previous_user = [], None
        for row in self.chats.get_ai_messages(chat_id)[:-1]:          # all but the new question
            if row["role"] == "user":
                previous_user = row["content"]
            elif row.get("source") == "llm" and previous_user is not None:
                pairs.append((previous_user, row["content"]))
                previous_user = None
            else:
                previous_user = None
        return pairs[-LLM_HISTORY_PAIRS:]

    def save_reply(self, chat_id: int, text: str, source: Optional[str] = None) -> Optional[Message]:
        """Store the assistant's (possibly cut-short) reply and return it."""
        self._check_owner(chat_id)
        text = str(text).strip()
        if not text:
            return None
        message_id = self.chats.add_ai_message(chat_id, "assistant", text, source)
        return Message(role="assistant", content=text, id=message_id, source=source or "")

    def auto_title(self, chat_id: int) -> Optional[str]:
        """Title a fresh chat after its first question (first 40 characters)."""
        chat = self._check_owner(chat_id)
        if chat["title"] and chat["title"] != DEFAULT_TITLE:
            return None
        first = next((m for m in self.chats.get_ai_messages(chat_id) if m["role"] == "user"), None)
        if first is None:
            return None
        title = " ".join(first["content"].split())
        title = title if len(title) <= TITLE_LENGTH else title[:TITLE_LENGTH].rstrip() + "…"
        self.chats.update_ai_chat_title(chat_id, title)
        return title
