"""Document summarization with BART-large-CNN (HuggingFace).

The model is loaded lazily on the first :meth:`Summarizer.summarize` call and is
then kept warm for the lifetime of the instance, so the screen creates one
``Summarizer`` and reuses it.

The model is driven directly (``AutoTokenizer`` + ``AutoModelForSeq2SeqLM`` +
``generate``) rather than through ``pipeline("summarization", ...)``: the
installed transformers 5.x removed that pipeline task (together with
``text2text-generation``), while the model classes and ``generate`` are stable
across 4.x and 5.x.  Working directly also gives us the tokenizer for chunking.

Loading and inference are slow - and the very first call downloads ~1.6 GB of
weights - so callers must run ``summarize()`` off the GUI thread
(see :class:`assistant.ai_worker.AIWorker`).
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

BART_MODEL_NAME = "facebook/bart-large-cnn"
MAX_INPUT_TOKENS = 1024          # BART's hard input limit
TARGET_SUMMARY_TOKENS = 200      # soft target for output length
MIN_SUMMARY_TOKENS = 60
MAX_SUMMARY_TOKENS = 300

SHORT_INPUT_TOKENS = 150         # below this, summarise in one pass
NUM_BEAMS = 4                    # beam search, as BART-large-CNN expects

# huggingface_hub 1.x prefers its new "Xet" transfer backend, which stalled at
# 0 bytes on this machine (measured: no progress for 15+ minutes) while the
# classic HTTPS downloader fetched the same file at ~1.2 MB/s.  Disable Xet by
# default so the first run makes progress; set HF_HUB_DISABLE_XET=0 to opt back
# in (an explicit value always wins over this default).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

#: Flipped to True once a model has been loaded; lets the UI tell the user that
#: the first run has to download the weights.
summarizer_loaded = False


def _import_stack():
    """Import torch and BART's concrete classes.

    Deliberately avoids ``AutoTokenizer`` / ``AutoModelForSeq2SeqLM``: the
    auto-classes resolve *every* tokenizer in transformers, which drags in
    sentencepiece's native extension - and on this machine that extension cannot
    be loaded once Qt is up (measured: access violation 0xC0000005 when importing
    sentencepiece after PyQt5).  In transformers 5 ``BartTokenizer`` is an alias
    of the fast Roberta BPE tokenizer, so sentencepiece is not needed at all.
    """
    import torch

    from transformers.models.bart.modeling_bart import BartForConditionalGeneration
    from transformers.models.bart.tokenization_bart import BartTokenizer

    return torch, BartTokenizer, BartForConditionalGeneration


class Summarizer:
    """Lazy-loading BART-large-CNN wrapper for document summarization."""

    def __init__(self, device=None):
        # Device detection imports torch (~2s the first time), so it is deferred
        # to _load(): constructing a Summarizer on the GUI thread must not block.
        self._device = device
        self._model = None       # loaded lazily
        self._tokenizer = None

    # ------------------------------------------------------------------ #
    #  Setup
    # ------------------------------------------------------------------ #
    @staticmethod
    def _detect_device():
        """'cuda' when a GPU is usable, otherwise 'cpu'.

        torch is imported here (not at module import time) so the rest of the
        application still runs on a machine without the deep-learning stack.
        """
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    @classmethod
    def is_loaded(cls):
        """True once a model has been loaded (used to detect the first run)."""
        return summarizer_loaded

    def _load(self):
        """Build the tokenizer + model once. Raises RuntimeError on failure."""
        global summarizer_loaded

        if self._model is not None:
            return

        if self._device is None:
            # Resolved here so the torch import happens on the worker thread.
            self._device = self._detect_device()

        try:
            _torch, tokenizer_class, model_class = _import_stack()
        except Exception as error:
            raise RuntimeError(
                f"The summarization stack is unavailable "
                f"({type(error).__name__}: {error}). Install it with:  "
                f"pip install torch transformers"
            )

        try:
            # the installed app ships a local copy (models/hf/...); development uses the hub cache
            from app_paths import hf_model

            source, local_only = hf_model(BART_MODEL_NAME)
            self._tokenizer = tokenizer_class.from_pretrained(source, local_files_only=local_only)
            self._model = model_class.from_pretrained(source, local_files_only=local_only)
            self._model.to(self._device)
            self._model.eval()
            # The repo's generation config sets max_length=142/min_length=56,
            # which would fight the per-chunk token budgets below and make
            # transformers print a conflict warning on every call.
            self._model.generation_config.max_length = None
            self._model.generation_config.min_length = None
        except Exception as error:
            self._model = None
            self._tokenizer = None
            raise RuntimeError(f"Could not load summarization model: {error}")

        summarizer_loaded = True

    # ------------------------------------------------------------------ #
    #  Chunking helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _split_sentences(text):
        """Split on sentence enders, keeping punctuation with its sentence."""
        parts = re.split(r"(?<=[.!?…])\s+", text)
        return [part for part in parts if part.strip()]

    def _count_tokens(self, text):
        """Token count for a short piece of text (sentences, not whole files)."""
        if self._tokenizer is None:
            return max(1, len(text) // 4)  # rough fallback: ~4 chars per token
        return len(self._tokenizer.encode(text, add_special_tokens=False))

    def _split_long_sentence(self, sentence, budget):
        """Hard-split a sentence that alone exceeds BART's window."""
        if self._tokenizer is None:
            size = budget * 4
            return [sentence[i:i + size] for i in range(0, len(sentence), size)]

        ids = self._tokenizer.encode(sentence, add_special_tokens=False)
        return [
            self._tokenizer.decode(ids[start:start + budget], skip_special_tokens=True)
            for start in range(0, len(ids), budget)
        ]

    def _build_chunks(self, text):
        """Group sentences so every chunk stays under ``MAX_INPUT_TOKENS``."""
        budget = MAX_INPUT_TOKENS - 8  # headroom for the special tokens
        chunks = []
        current = []
        current_tokens = 0

        for sentence in self._split_sentences(text):
            count = self._count_tokens(sentence)

            if count > budget:
                if current:
                    chunks.append(" ".join(current))
                    current, current_tokens = [], 0
                chunks.extend(self._split_long_sentence(sentence, budget))
                continue

            if current_tokens + count > budget:
                chunks.append(" ".join(current))
                current, current_tokens = [], 0

            current.append(sentence)
            current_tokens += count

        if current:
            chunks.append(" ".join(current))
        return [chunk for chunk in chunks if chunk.strip()]

    @staticmethod
    def _min_length_for(chunk, tokens):
        """``MIN_SUMMARY_TOKENS``, capped so a short chunk is not padded out."""
        return max(5, min(MIN_SUMMARY_TOKENS, tokens // 2))

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #
    def summarize(self, text: str) -> str:
        """Summarize arbitrary-length text.

        Splits the input on sentence boundaries into chunks of at most
        ``MAX_INPUT_TOKENS`` tokens, summarizes each one and returns the
        summaries joined by a blank line.  A chunk that fails is reported
        inline instead of aborting the whole summary.
        """
        if not text or not text.strip():
            raise ValueError("No text to summarize")

        self._load()

        sentences = self._split_sentences(text)
        sentence_tokens = [self._count_tokens(sentence) for sentence in sentences]
        total_tokens = sum(sentence_tokens)

        if total_tokens <= SHORT_INPUT_TOKENS:
            chunks = [text.strip()]
        else:
            chunks = self._build_chunks(text)
        if not chunks:
            chunks = [text.strip()]

        # A single short pass does not need the full output budget.
        max_new = MAX_SUMMARY_TOKENS if len(chunks) > 1 else TARGET_SUMMARY_TOKENS

        summaries = []
        for chunk in chunks:
            try:
                summaries.append(self._summarize_chunk(chunk, max_new))
            except Exception as error:
                summaries.append(f"[chunk skipped: {type(error).__name__}: {error}]")

        return "\n\n".join(summaries)

    def _summarize_chunk(self, chunk, max_new_tokens):
        """Run BART's beam search over one chunk and decode the result."""
        import torch

        encoded = self._tokenizer(
            chunk,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_INPUT_TOKENS,
        )
        encoded = {key: value.to(self._device) for key, value in encoded.items()}

        with torch.no_grad():
            generated = self._model.generate(
                **encoded,
                max_new_tokens=max_new_tokens,
                min_new_tokens=self._min_length_for(chunk, self._count_tokens(chunk)),
                num_beams=NUM_BEAMS,
                do_sample=False,
                length_penalty=2.0,
                no_repeat_ngram_size=3,
                early_stopping=True,
            )

        summary = self._tokenizer.decode(generated[0], skip_special_tokens=True)
        return summary.strip() or "[chunk skipped: empty summary]"

    def unload(self):
        """Free GPU memory (optional but nice)."""
        global summarizer_loaded

        self._model = None
        self._tokenizer = None
        summarizer_loaded = False
        try:
            import gc

            import torch

            torch.cuda.empty_cache()
            gc.collect()
        except Exception:
            logger.debug("Could not free GPU memory", exc_info=True)


if __name__ == "__main__":
    s = Summarizer()
    sample = ("Artificial intelligence is transforming industries. "
              "It enables automation, improves decision-making, and "
              "creates new opportunities. However, it also raises "
              "concerns about privacy, jobs, and ethics. Companies "
              "and governments are working together to set standards. "
              "The future of AI depends on how responsibly we deploy it.")
    print(s.summarize(sample))
