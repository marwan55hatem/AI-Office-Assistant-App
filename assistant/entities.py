"""Finding names in a question: which task, which employee.

Used by the answer engine, and also *before* classification: real task and
employee names are replaced by the placeholders ``taskx`` / ``personx`` so that
the classifier sees "how is personx doing" whatever the person is called.
"""

import difflib
import re

from assistant.intent_model import normalize
from assistant.lexicon import concept_tags

TASK_MASK = "taskx"
PERSON_MASK = "personx"

STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "at", "my",
    "with", "by", "is", "it", "this", "that", "new", "task", "tasks", "do",
    "up", "out", "from", "about", "please", "me", "i", "you", "your",
}


def words(text):
    """Normalised words of ``text``."""
    return re.findall(r"\w+", normalize(text), re.UNICODE)


def _significant(text):
    return [w for w in words(text) if w not in STOPWORDS and len(w) >= 2]


def _close(a, b):
    """Same word, allowing a small typo in longer words."""
    if a == b:
        return True
    return len(a) >= 4 and len(b) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.84


_VOCAB = None


def vocabulary():
    """Every word that appears in the example questions or the lexicon."""
    global _VOCAB
    if _VOCAB is None:
        from assistant.intents import BANK
        from assistant.lexicon import _CONCEPT_PATTERNS

        vocab = set()
        for phrases in BANK.values():
            for phrase in phrases:
                vocab.update(words(phrase))
        for pattern in _CONCEPT_PATTERNS.values():
            vocab.update(w for w in re.findall(r"[^\W\d_]{3,}", normalize(pattern)))
        vocab -= {TASK_MASK, PERSON_MASK}
        _VOCAB = vocab
    return _VOCAB


def autocorrect(text):
    """Fix obvious typos ("waht taks" -> "what tasks") against the known words.

    Only words of 4+ letters that the assistant has never seen are touched, and
    only when a known word is very similar; placeholders and short words stay.
    """
    vocab = vocabulary()
    out = []
    for part in re.findall(r"\w+|\W+", text, re.UNICODE):
        if re.match(r"\w", part) and len(part) >= 3 and part not in vocab \
                and part not in (TASK_MASK, PERSON_MASK) and part.isascii() and not part.isdigit():
            close = difflib.get_close_matches(part, vocab, n=1, cutoff=0.78)
            if close:
                part = close[0]
        out.append(part)
    return "".join(out)


def mask_entities(text, people=(), tasks=()):
    """Replace known employee names / task-title words by ``personx`` / ``taskx``.

    Words that are themselves a concept of the lexicon ("report", "team") are
    left alone, so a task called "Weekly report" does not hide the word "report".
    """
    person_words = {w for name in people for w in words(name) if len(w) >= 3}
    task_words = {w for title in tasks for w in _significant(title)}
    out = []
    for word in re.findall(r"\w+|\W+", normalize(text), re.UNICODE):
        if not re.match(r"\w", word):
            out.append(word)
            continue
        if any(_close(word, p) for p in person_words):
            out.append(PERSON_MASK)
        elif (word in task_words or any(_close(word, t) for t in task_words)) \
                and not concept_tags(word) and word not in STOPWORDS:
            out.append(TASK_MASK)
        else:
            out.append(word)
    masked = "".join(out)
    masked = re.sub(r"\b(%s)(\s+\1)+\b" % "|".join((PERSON_MASK, TASK_MASK)), r"\1", masked)
    return masked


def match_people(text, people):
    """Employees mentioned in ``text`` (``people`` = dicts with ``full_name``).

    A first name, last name or full name matches; small typos are tolerated.
    """
    spoken = words(text)
    found = []
    for person in people:
        parts = [w for w in words(person["full_name"]) if len(w) >= 3]
        if any(_close(word, part) for word in spoken for part in parts):
            found.append(person)
    return found


def match_task(text, tasks):
    """The task (``dict`` with ``title``) the question is about, or ``None``.

    Scores each task by how many of its significant title words appear in the
    question; the best one wins when at least half of its words were mentioned.
    """
    spoken = words(text)
    best, best_score = None, 0.0
    for task in tasks:
        title_words = _significant(task["title"])
        if not title_words:
            continue
        hits = sum(1 for t in title_words if any(_close(w, t) for w in spoken))
        score = hits / len(title_words)
        if score > best_score:
            best, best_score = task, score
    return best if best_score >= 0.5 else None
