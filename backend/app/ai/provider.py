"""The online chat model, behind a small interface so tests use a fake.

``GroqChatModel`` calls Groq's OpenAI-compatible chat API with streaming. Before the
first token it retries rate limits (429) and server errors with backoff, honouring
``retry-after``. Only status codes are logged, never the prompt or the answer.
"""
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

logger = logging.getLogger("office.ai")


class ModelUnavailable(Exception):
    """The model cannot answer now (not configured, rate-limited after retries, provider error)."""

    def __init__(self, message: str, busy: bool = False):
        super().__init__(message)
        self.busy = busy


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatModel:
    name = "model"

    def stream(self, messages: list[dict], max_tokens: int) -> Iterator[tuple[str, object]]:
        """Yields ``("delta", text)`` pieces and finally ``("usage", Usage)``."""
        raise NotImplementedError


class FakeChatModel(ChatModel):
    """Used by the tests: answers with a fixed text and remembers what it was asked."""
    name = "fake"

    def __init__(self, reply="Hello from the fake model.", fail: ModelUnavailable | None = None):
        self.reply = reply
        self.fail = fail
        self.calls: list[list[dict]] = []

    def stream(self, messages, max_tokens):
        self.calls.append(messages)
        if self.fail:
            raise self.fail
        for word in self.reply.split(" "):
            yield "delta", word + " "
        yield "usage", Usage(prompt_tokens=sum(len(m["content"]) for m in messages) // 4,
                             completion_tokens=len(self.reply) // 4)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class GroqChatModel(ChatModel):
    RETRY_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str, model: str, base_url: str, reasoning_effort: str | None,
                 attempts: int = 3, http: httpx.Client | None = None):
        self.name = model
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.attempts = attempts
        self.http = http or httpx.Client(base_url=base_url, timeout=httpx.Timeout(60.0, connect=10.0),
                                         headers={"Authorization": f"Bearer {api_key}"})

    def _payload(self, messages, max_tokens, minimal=False):
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "max_completion_tokens": max_tokens, "temperature": 0.3}
        if not minimal:
            payload["stream_options"] = {"include_usage": True}
            payload["include_reasoning"] = False
            if self.reasoning_effort:
                payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def stream(self, messages, max_tokens):
        minimal = False
        for attempt in range(1, self.attempts + 1):
            request = self.http.build_request("POST", "/chat/completions",
                                              json=self._payload(messages, max_tokens, minimal))
            try:
                response = self.http.send(request, stream=True)
            except httpx.TransportError:
                logger.warning("AI provider unreachable (attempt %d)", attempt)
                if attempt == self.attempts:
                    raise ModelUnavailable("The AI service cannot be reached right now.") from None
                time.sleep(2 ** attempt)
                continue
            if response.status_code == 200:
                yield from self._read(response, messages)
                return
            status = response.status_code
            retry_after = response.headers.get("retry-after")
            response.read()
            response.close()
            logger.warning("AI provider answered %d (attempt %d)", status, attempt)
            if status == 400 and not minimal:
                minimal = True                    # an optional field was refused: retry without them
                continue
            if status in self.RETRY_STATUSES and attempt < self.attempts:
                wait = min(float(retry_after), 10.0) if retry_after else 2.0 ** attempt
                time.sleep(wait)
                continue
            if status == 429:
                raise ModelUnavailable("The AI service is busy. Please try again in a minute.", busy=True)
            raise ModelUnavailable("The AI service could not answer right now.")
        raise ModelUnavailable("The AI service could not answer right now.")

    def _read(self, response, messages):
        usage = None
        written = 0
        try:
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                found = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
                if found:
                    usage = Usage(found.get("prompt_tokens", 0), found.get("completion_tokens", 0))
                for choice in chunk.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")   # reasoning text is ignored
                    if text:
                        written += len(text)
                        yield "delta", text
        finally:
            response.close()
        if usage is None:      # the provider did not report usage: estimate it
            usage = Usage(estimate_tokens("".join(m["content"] for m in messages)), max(1, written // 4))
        yield "usage", usage


_model: ChatModel | None = None


def get_chat_model() -> ChatModel | None:
    """The configured model, or None when no key is set (the chat then reports it is off)."""
    global _model
    if _model is None:
        settings = get_settings()
        if settings.ai_fake_model and settings.environment != "production":
            _model = FakeChatModel("This answer comes from the development stand-in model, not from Groq.")
            return _model
        if not settings.groq_api_key:
            return None
        _model = GroqChatModel(settings.groq_api_key.get_secret_value(), settings.groq_model,
                               settings.groq_base_url, settings.ai_reasoning_effort)
    return _model


def set_chat_model(model: ChatModel | None) -> None:
    """Replace the model (tests)."""
    global _model
    _model = model
