"""The language model as the chat screen sees it: a small, replaceable service.

The screen needs only five things from the model -- is it loaded, on which device,
start loading it, start writing an answer, and free it when idle.  Depending on this
class (and not on ``model_manager`` / ``workers`` directly) means the screen can be
given any other object with the same methods -- a fake in tests, or another model
later -- and the heavy ``torch`` import stays out of the screen's module.
"""

from typing import Dict, List, Optional


class ModelService:
    """Facade over :class:`llm.model_manager.LLMManager` and the Qt workers."""

    def is_loaded(self) -> bool:
        """True when the model is in memory and can answer at once."""
        from llm.model_manager import get_manager

        return get_manager().loaded

    def device(self) -> Optional[str]:
        """``"cuda"``, ``"cpu"`` or ``None`` when nothing is loaded."""
        from llm.model_manager import get_manager

        return get_manager().device

    def create_load_worker(self, parent=None):
        """A not-yet-started ``QThread`` with ``loaded(device)`` / ``failed(message)`` signals."""
        from llm.workers import LoadWorker

        return LoadWorker(parent)

    def create_generate_worker(self, messages: List[Dict[str, str]], parent=None):
        """A not-yet-started ``QThread`` with ``piece`` / ``done`` / ``failed`` signals and ``stop()``."""
        from llm.workers import GenerateWorker

        return GenerateWorker(messages, parent)

    def unload_if_idle(self, seconds: Optional[float] = None) -> bool:
        """Free the model's memory if it has been unused for ``seconds`` (default: the config value)."""
        from llm.model_manager import get_manager

        return get_manager().unload_if_idle(seconds)
