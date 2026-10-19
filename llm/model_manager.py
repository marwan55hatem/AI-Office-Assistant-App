"""Loads the local language model and streams answers from it.

Qt-free on purpose (like ``assistant/``): the manager knows nothing about
windows, so it can be tested on its own.  It never touches the database --
the caller passes plain chat messages in and gets plain text pieces out.
"""

import threading
import time

from llm import config
from typing import Dict, Iterator, List, Optional

try:                                    # the app imports this lazily; heavy libs load on first use
    import torch
except Exception:                       # pragma: no cover
    torch = None


class ModelNotAvailable(Exception):
    """The model files are missing or could not be loaded."""


class Cancelled(Exception):
    """Generation was stopped by the user."""


class LLMManager:
    """One shared model.  ``load()`` is slow, ``stream()`` yields text as it is written."""

    def __init__(self, model_dir=None):
        self.model_dir = model_dir or config.MODEL_DIR
        self.model = None
        self.tokenizer = None
        self.device = None              # "cuda" or "cpu" once loaded
        self.load_seconds = 0.0
        self.last_used = 0.0
        self._lock = threading.Lock()   # one load / generation at a time
        self._cancel = threading.Event()

    # ------------------------------------------------------------------ status
    @property
    def loaded(self):
        """True while the model is in memory."""
        return self.model is not None

    def available(self) -> bool:
        """True when the model files are on disk."""
        import os
        return os.path.isfile(os.path.join(self.model_dir, "model.safetensors")) and \
            os.path.isfile(os.path.join(self.model_dir, "config.json"))

    def vram_used_gb(self) -> float:
        """GPU memory held by the model in GB (0 on CPU or when unloaded)."""
        if torch is None or self.device != "cuda":
            return 0.0
        return torch.cuda.memory_allocated() / 1e9

    def status(self) -> str:
        """'missing' (no files), 'not loaded' or 'ready'."""
        if not self.available():
            return "missing"
        return "ready" if self.loaded else "not loaded"

    # ------------------------------------------------------------------ load / unload
    def _pick_device(self):
        if torch is not None and torch.cuda.is_available():
            free, _total = torch.cuda.mem_get_info()
            if free / 1e9 >= config.MIN_FREE_VRAM_GB:
                return "cuda"
        return "cpu"

    def load(self, device: Optional[str] = None) -> str:
        """Load the model (about 5-15 s the first time).  Safe to call twice."""
        with self._lock:
            if self.loaded:
                return self.device
            if torch is None:
                raise ModelNotAvailable("PyTorch is not installed.")
            if not self.available():
                raise ModelNotAvailable("The model files were not found in %s" % self.model_dir)
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from transformers.utils import logging as hf_logging
            hf_logging.disable_progress_bar()
            started = time.monotonic()
            device = device or self._pick_device()
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir, local_files_only=True)
                dtype = torch.float16 if device == "cuda" else torch.bfloat16
                model = AutoModelForCausalLM.from_pretrained(
                    self.model_dir, dtype=dtype, local_files_only=True)
                model.to(device).eval()
            except Exception as error:
                self.model = self.tokenizer = None
                if device == "cuda":
                    torch.cuda.empty_cache()
                raise ModelNotAvailable("Could not load the model: %s" % error)
            self.model, self.device = model, device
            self.load_seconds = time.monotonic() - started
            self.last_used = time.monotonic()
            return device

    def unload(self) -> None:
        """Free the memory (the GPU is shared with the camera detection)."""
        with self._lock:
            self.model = self.tokenizer = None
            if torch is not None and torch.cuda.is_available():
                import gc
                gc.collect()
                torch.cuda.empty_cache()
            self.device = None

    def unload_if_idle(self, seconds: Optional[float] = None) -> bool:
        """Unload after ``seconds`` without use.  Returns True if it unloaded."""
        seconds = config.IDLE_UNLOAD_SECONDS if seconds is None else seconds
        if self.loaded and not self._lock.locked() and time.monotonic() - self.last_used >= seconds:
            self.unload()
            return True
        return False

    # ------------------------------------------------------------------ generate
    def cancel(self) -> None:
        """Ask the running generation to stop (it ends within one token)."""
        self._cancel.set()

    def _build_inputs(self, messages):
        """Chat template + keep the prompt within MAX_INPUT_TOKENS (oldest turns go first)."""
        msgs = list(messages)
        while True:
            text = self.tokenizer.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
            ids = self.tokenizer(text, return_tensors="pt")
            if ids["input_ids"].shape[1] <= config.MAX_INPUT_TOKENS or len(msgs) <= 2:
                return ids
            drop = 1 if msgs[0].get("role") == "system" else 0     # keep the system prompt
            del msgs[drop]

    def stream(self, messages: List[Dict[str, str]], max_new_tokens: Optional[int] = None) -> Iterator[str]:
        """Yield the answer to ``messages`` piece by piece.

        ``messages`` is ``[{"role": "system"|"user"|"assistant", "content": str}, ...]``.
        Call ``cancel()`` from another thread to stop; the generator then ends.
        """
        if not self.loaded:
            self.load()
        from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer

        manager = self

        class _Stop(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return manager._cancel.is_set()

        with self._lock:
            self._cancel.clear()
            self.last_used = time.monotonic()
            inputs = self._build_inputs(messages).to(self.device)
            streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
            failure = []

            def run():
                try:
                    with torch.no_grad():
                        self.model.generate(
                            **inputs, streamer=streamer,
                            max_new_tokens=max_new_tokens or config.MAX_NEW_TOKENS,
                            do_sample=config.TEMPERATURE > 0,
                            temperature=config.TEMPERATURE, top_p=config.TOP_P,
                            repetition_penalty=config.REPETITION_PENALTY,
                            stopping_criteria=StoppingCriteriaList([_Stop()]),
                            pad_token_id=self.tokenizer.eos_token_id)
                except Exception as error:      # e.g. out of memory
                    failure.append(error)
                    streamer.end()

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                for piece in streamer:
                    if piece:
                        yield piece
                    if self._cancel.is_set():
                        break
            finally:
                self._cancel.set()              # make sure a half-read generation stops
                worker.join()
                self.last_used = time.monotonic()
            if failure:
                if self.device == "cuda":
                    torch.cuda.empty_cache()
                raise ModelNotAvailable("Generation failed: %s" % failure[0])

    def ask(self, messages: List[Dict[str, str]], max_new_tokens: Optional[int] = None) -> str:
        """Whole answer as one string (for tests)."""
        return "".join(self.stream(messages, max_new_tokens))


_shared = None


def get_manager() -> LLMManager:
    """The one model manager the whole app shares."""
    global _shared
    if _shared is None:
        _shared = LLMManager()
    return _shared
