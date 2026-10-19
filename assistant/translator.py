"""MarianMT translation with one cached model per language pair.

The models are the Helsinki-NLP ``opus-mt-*`` pair models.  They are loaded
lazily on first use and then kept in a class-level cache, so switching
EN->AR -> EN->FR -> EN->AR does not reload anything.

Two transformers-5 notes carried over from the summarizer:

* the ``translation`` pipeline no longer exists, so ``MarianTokenizer`` and
  ``MarianMTModel`` are used directly;
* ``MarianTokenizer`` imports **sentencepiece** at module import time, and on
  this machine sentencepiece cannot be loaded after Qt (access violation), so
  ``main.py`` pre-imports it before PyQt5.  Everything heavy is imported inside
  the worker thread at call time.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# The hub's new "Xet" transfer backend stalls on this network; the classic
# HTTPS downloader works (same workaround as assistant/summarizer.py).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

SUPPORTED_LANGS = {
    "English": "en",
    "Arabic": "ar",
    "French": "fr",
    "German": "de",
}

MAX_INPUT_CHARS = 5000
MAX_INPUT_TOKENS = 420        # Marian's practical window (512 minus specials)
MAX_OUTPUT_TOKENS = 512
NUM_BEAMS = 4
PIVOT_LANG = "en"             # pairs without a direct model route through English

#: Direct pair models.  Every combination of en/ar/fr/de was verified to exist
#: on the Hub (each repo carries a pytorch_model.bin plus source/target .spm).
DIRECT_MODELS = {
    ("en", "ar"): "Helsinki-NLP/opus-mt-en-ar",
    ("en", "fr"): "Helsinki-NLP/opus-mt-en-fr",
    ("en", "de"): "Helsinki-NLP/opus-mt-en-de",
    ("ar", "en"): "Helsinki-NLP/opus-mt-ar-en",
    ("fr", "en"): "Helsinki-NLP/opus-mt-fr-en",
    ("de", "en"): "Helsinki-NLP/opus-mt-de-en",
    ("ar", "fr"): "Helsinki-NLP/opus-mt-ar-fr",
    ("ar", "de"): "Helsinki-NLP/opus-mt-ar-de",
    ("fr", "ar"): "Helsinki-NLP/opus-mt-fr-ar",
    ("de", "ar"): "Helsinki-NLP/opus-mt-de-ar",
    ("fr", "de"): "Helsinki-NLP/opus-mt-fr-de",
    ("de", "fr"): "Helsinki-NLP/opus-mt-de-fr",
}

_ipv4_checked = False


def _prefer_ipv4_if_ipv6_is_broken(host="huggingface.co"):
    """Force IPv4 resolution when IPv6 lookup is broken.

    On this machine IPv6 name resolution fails while IPv4 works (0/8 vs 8/8),
    which makes huggingface_hub abort long downloads with
    ``getaddrinfo failed``.  The check is cheap, done once, and leaves systems
    with working IPv6 untouched (set HF_SKIP_IPV4_FIX=1 to skip it entirely).
    """
    global _ipv4_checked

    if _ipv4_checked or os.environ.get("HF_SKIP_IPV4_FIX") == "1":
        return False
    _ipv4_checked = True

    try:
        import socket

        try:
            socket.getaddrinfo(host, 443, socket.AF_INET6, socket.SOCK_STREAM)
            return False  # IPv6 resolves: do not interfere
        except Exception:
            logger.debug("IPv6 lookup failed; assuming it is not usable", exc_info=True)

        original = socket.getaddrinfo

        def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
            return original(host, port, socket.AF_INET, type, proto, flags)

        socket.getaddrinfo = _ipv4_only
        return True
    except Exception:
        return False


def _split_paragraphs(text):
    return [block for block in re.split(r"\n\s*\n", text) if block.strip()]


def _split_sentences(text):
    """Split on sentence enders, keeping punctuation with its sentence."""
    parts = re.split(r"(?<=[.!?…؟])\s+", text)
    return [part for part in parts if part.strip()]


class Translator:
    """Lazy-loading MarianMT wrapper, cached per language pair."""

    _cache = {}   # {(src_code, tgt_code): (tokenizer, model, device)}

    def __init__(self, src_lang, tgt_lang):
        if src_lang not in SUPPORTED_LANGS:
            raise ValueError(f"Unsupported source language: {src_lang}")
        if tgt_lang not in SUPPORTED_LANGS:
            raise ValueError(f"Unsupported target language: {tgt_lang}")

        self.src_name = src_lang
        self.tgt_name = tgt_lang
        self.src_code = SUPPORTED_LANGS[src_lang]
        self.tgt_code = SUPPORTED_LANGS[tgt_lang]
        self._key = (self.src_code, self.tgt_code)
        self._model_name = self._resolve_model_name()
        self._legs = self._resolve_legs()

    # ------------------------------------------------------------------ #
    #  Model resolution
    # ------------------------------------------------------------------ #
    def _resolve_model_name(self):
        """Return the direct HuggingFace model id, or None if a pivot is needed."""
        return DIRECT_MODELS.get(self._key)

    def _resolve_legs(self):
        """Return the [(src, tgt, model_name), ...] chain for this pair.

        One entry when a direct model exists, otherwise two entries pivoting
        through English (e.g. a pair such as xx->yy that has no direct model).
        """
        direct = self._resolve_model_name()
        if direct:
            return [(self.src_code, self.tgt_code, direct)]

        if self.src_code == PIVOT_LANG or self.tgt_code == PIVOT_LANG:
            raise ValueError(
                f"No translation model for {self.src_name}->{self.tgt_name}"
            )

        first = DIRECT_MODELS.get((self.src_code, PIVOT_LANG))
        second = DIRECT_MODELS.get((PIVOT_LANG, self.tgt_code))
        if not first or not second:
            raise ValueError(
                f"No translation model for {self.src_name}->{self.tgt_name}"
            )
        return [
            (self.src_code, PIVOT_LANG, first),
            (PIVOT_LANG, self.tgt_code, second),
        ]

    @property
    def uses_pivot(self):
        """True when the pair is translated through English."""
        return len(self._legs) > 1

    @property
    def model_names(self):
        """Hugging Face model names of the translation legs (one or two)."""
        return [model_name for _src, _tgt, model_name in self._legs]

    # ------------------------------------------------------------------ #
    #  Loading
    # ------------------------------------------------------------------ #
    @classmethod
    def _load_pair(cls, src_code, tgt_code, model_name):
        """Load (or fetch from the cache) the tokenizer + model for one pair."""
        key = (src_code, tgt_code)
        if key in cls._cache:
            return cls._cache[key]

        _prefer_ipv4_if_ipv6_is_broken()

        import torch
        from transformers.models.marian.modeling_marian import MarianMTModel
        from transformers.models.marian.tokenization_marian import MarianTokenizer

        try:
            from app_paths import hf_model

            source, local_only = hf_model(model_name)     # local copy first (installed app is offline)
            tokenizer = MarianTokenizer.from_pretrained(source, local_files_only=local_only)
            model = MarianMTModel.from_pretrained(source, local_files_only=local_only)
        except Exception as error:
            raise RuntimeError(
                f"Could not load the translation model '{model_name}' "
                f"({type(error).__name__}: {error}). It is downloaded on first "
                f"use, so check the internet connection."
            )

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        model.eval()
        # opus-mt ships max_length/min_length in generation_config.json, which
        # would fight the token budgets below and print a warning per call.
        model.generation_config.max_length = None
        model.generation_config.min_length = None

        cls._cache[key] = (tokenizer, model, device)
        return cls._cache[key]

    # ------------------------------------------------------------------ #
    #  Translation
    # ------------------------------------------------------------------ #
    def _count_tokens(self, tokenizer, text):
        return len(tokenizer.encode(text, add_special_tokens=False))

    def _chunks(self, tokenizer, paragraph):
        """Group a paragraph's sentences into <= MAX_INPUT_TOKENS-token chunks."""
        chunks = []
        current = []
        current_tokens = 0

        for sentence in _split_sentences(paragraph) or [paragraph]:
            count = self._count_tokens(tokenizer, sentence)
            if current_tokens + count > MAX_INPUT_TOKENS and current:
                chunks.append(" ".join(current))
                current, current_tokens = [], 0
            current.append(sentence)
            current_tokens += count

        if current:
            chunks.append(" ".join(current))
        return chunks or [paragraph]

    def _translate_leg(self, tokenizer, model, device, text):
        """Translate one hop (src -> tgt) paragraph by paragraph."""
        import torch

        translated_paragraphs = []
        for paragraph in _split_paragraphs(text) or [text]:
            pieces = []
            for chunk in self._chunks(tokenizer, paragraph):
                encoded = tokenizer(
                    chunk,
                    return_tensors="pt",
                    truncation=True,
                    max_length=MAX_INPUT_TOKENS,
                    padding=True,
                )
                encoded = {key: value.to(device) for key, value in encoded.items()}
                with torch.no_grad():
                    generated = model.generate(
                        **encoded,
                        max_new_tokens=MAX_OUTPUT_TOKENS,
                        num_beams=NUM_BEAMS,
                        do_sample=False,
                        early_stopping=True,
                    )
                pieces.append(
                    tokenizer.decode(generated[0], skip_special_tokens=True).strip()
                )
            translated_paragraphs.append(" ".join(piece for piece in pieces if piece))
        return "\n\n".join(translated_paragraphs).strip()

    def translate(self, text: str) -> str:
        """Translate ``text`` (up to MAX_INPUT_CHARS), pivoting via English if needed."""
        if not text or not text.strip():
            raise ValueError("No text to translate")
        if len(text) > MAX_INPUT_CHARS:
            raise ValueError(
                f"Text is too long ({len(text):,} characters, maximum "
                f"{MAX_INPUT_CHARS:,})."
            )

        result = text
        for src_code, tgt_code, model_name in self._legs:
            tokenizer, model, device = self._load_pair(src_code, tgt_code, model_name)
            result = self._translate_leg(tokenizer, model, device, result)
        return result

    # ------------------------------------------------------------------ #
    #  Shutdown
    # ------------------------------------------------------------------ #
    @classmethod
    def unload(cls, src_lang=None, tgt_lang=None):
        """Free cached model(s): a single pair when given, otherwise all of them."""
        if src_lang and tgt_lang:
            cls._cache.pop((SUPPORTED_LANGS[src_lang], SUPPORTED_LANGS[tgt_lang]), None)
        else:
            cls._cache.clear()
        try:
            import gc

            import torch

            torch.cuda.empty_cache()
            gc.collect()
        except Exception:
            logger.debug("Could not free GPU memory", exc_info=True)


if __name__ == "__main__":
    t = Translator("English", "Arabic")
    print(t.translate("Hello, how are you today?"))
