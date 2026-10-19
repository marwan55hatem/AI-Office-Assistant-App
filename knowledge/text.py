"""Words and passages: tokenising for search, and cutting a document into chunks.

Qt-free and model-free.  English and Arabic are supported (Arabic letters are
unified the same way as in the rest of the assistant).
"""

import re
import unicodedata
from collections import namedtuple
from typing import List

_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
_TASHKEEL = re.compile("[ً-ٰٟـ]")

STOPWORDS = frozenset("""
a an the and or but if of to in on at by for with from as is are was were be been being am do does did
how what which who whom whose when where why can could should would will shall may might must
i me my we our you your he she it its they them their this that these those there here
about into over under than then so such not no yes any some each other more most very just also many much long often
tell explain describe give show please need want like use using used get make
في من على الى عن ما هو هي هذا هذه ذلك كيف ماذا هل ان او ثم مع كل
""".split())

Chunk = namedtuple("Chunk", "doc_id filename heading text")


def normalize(text: str) -> str:
    """Lower-case, NFKC, unified Arabic letters and no diacritics."""
    text = unicodedata.normalize("NFKC", str(text)).lower()
    return _TASHKEEL.sub("", text).translate(_AR_MAP)


def stem(word: str) -> str:
    """Very light stemming: ``layers -> layer``, ``pooling -> pool``, ``overfitting -> overfit``."""
    if not word.isascii() or len(word) < 5:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ional"):
        return word[:-2]                      # convolutional -> convolution
    for suffix in ("ing", "edly", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiouls":
        word = word[:-1]                      # overfitt -> overfit
    return word


def tokens(text: str, drop_stopwords: bool = True) -> List[str]:
    """Search terms of a text: lower-case, unified Arabic, stemmed, stopwords removed."""
    out = []
    for word in re.findall(r"\w+", normalize(text), re.UNICODE):
        if word.isdigit() and len(word) < 2:
            continue
        if drop_stopwords and word in STOPWORDS:
            continue
        out.append(stem(word))
    return out


# ---------------------------------------------------------------------- chunks
MAX_WORDS = 160          # a passage is about this long (a paragraph or two)
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")


def _blocks(text):
    """``[(heading, paragraph)]``: paragraphs with the Markdown heading they sit under.
    A fenced code block is never cut in the middle."""
    heading, blocks, current, in_code = "", [], [], False

    def flush():
        if current:
            blocks.append((heading, "\n".join(current).strip()))
            current.clear()

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            current.append(line)
            continue
        if in_code:
            current.append(line)
            continue
        match = _HEADING.match(line)
        if match:
            flush()
            heading = match.group(2).strip()
        elif not line.strip():
            flush()
        else:
            current.append(line)
    flush()
    return [(h, p) for h, p in blocks if p]


def _split_long(paragraph, limit):
    """Cut an over-long paragraph at sentence ends (code blocks are kept whole)."""
    if paragraph.lstrip().startswith("```") or len(paragraph.split()) <= limit * 1.5:
        return [paragraph]
    pieces, current = [], []
    for sentence in re.split(r"(?<=[.!?؟])\s+", paragraph):
        if current and len(" ".join(current + [sentence]).split()) > limit:
            pieces.append(" ".join(current))
            current = []
        current.append(sentence)
    if current:
        pieces.append(" ".join(current))
    return pieces


def split_document(doc_id: int, filename: str, text: str, max_words: int = MAX_WORDS) -> List[Chunk]:
    """Cut a document into :class:`Chunk` passages of about ``max_words`` words.

    Paragraphs under the same Markdown heading are merged until a passage is full, so
    a passage reads like a small section; the heading is kept with it.
    """
    chunks, current, words, current_heading = [], [], 0, None

    def emit():
        if current:
            chunks.append(Chunk(doc_id, filename, current_heading or "", "\n\n".join(current)))

    for heading, paragraph in _blocks(text):
        for piece in _split_long(paragraph, max_words):
            size = len(piece.split())
            if current and (heading != current_heading or words + size > max_words):
                emit()
                current, words = [], 0
            current_heading = heading
            current.append(piece)
            words += size
    emit()
    return chunks
