"""The knowledge base: documents in the database + a BM25 search over them.

Privacy: a document is either visible to *everyone* or to *managers only*.  The
filter is applied **before** anything is indexed or searched -- an employee's index
is built only from the 'everyone' documents, so a manager-only passage can never
come up in an employee's search, in a prompt, or in a reply.
"""

import os

from knowledge.bm25 import BM25Index
from knowledge.text import split_document
from typing import Any, Dict, List, Optional, Tuple

ALLOWED_EXTENSIONS = (".txt", ".md", ".markdown")
MAX_FILE_BYTES = 2 * 1024 * 1024
VISIBILITIES = ("everyone", "managers")
PASSAGE_CHARS = 900             # longest passage shown to the model / in a reply
TOTAL_CHARS = 2400              # all passages together


class KnowledgeError(Exception):
    """A document could not be added (the message is meant to be shown to the user)."""


def read_text_file(path: str) -> Tuple[str, str]:
    """The text of a ``.txt`` / ``.md`` file, or :class:`KnowledgeError`."""
    name = os.path.basename(path)
    if os.path.splitext(name)[1].lower() not in ALLOWED_EXTENSIONS:
        raise KnowledgeError("%s: only .txt and .md files can be added." % name)
    try:
        size = os.path.getsize(path)
        if size > MAX_FILE_BYTES:
            raise KnowledgeError("%s is too large (%.1f MB; the limit is %d MB)." % (name, size / 1e6, MAX_FILE_BYTES // 2**20))
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as error:
        raise KnowledgeError("%s could not be read: %s" % (name, error))
    if b"\x00" in raw:
        raise KnowledgeError("%s is not a text file." % name)
    for encoding in ("utf-8-sig", "utf-16", "cp1256", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise KnowledgeError("%s is empty." % name)
    return name, text


class KnowledgeBase:
    """Add / remove / search documents for one database."""

    def __init__(self, db):
        self.db = db
        self.repo = db.knowledge           # only the document methods of the database
        self._cache = {}                # include_manager_only -> (signature, BM25Index)

    # ------------------------------------------------------------------ documents
    def add_file(self, path: str, visibility: str = "everyone", user_id: Optional[int] = None) -> Tuple[int, bool]:
        """Add (or replace) a document from a file.  Returns ``(doc_id, created)``."""
        name, text = read_text_file(path)
        return self.add_text(name, text, visibility, user_id)

    def add_text(self, filename: str, text: str, visibility: str = "everyone", user_id: Optional[int] = None) -> Tuple[int, bool]:
        """Add (or replace) a document from text; returns ``(doc_id, created)``."""
        if visibility not in VISIBILITIES:
            raise KnowledgeError("Visibility must be 'everyone' or 'managers'.")
        if not str(text).strip():
            raise KnowledgeError("%s is empty." % filename)
        return self.repo.upsert_knowledge_doc(filename, str(text).strip(), visibility, user_id)

    def remove(self, doc_id: int) -> bool:
        """Delete a document; True if it existed."""
        return self.repo.delete_knowledge_doc(doc_id)

    def set_visibility(self, doc_id: int, visibility: str) -> bool:
        """Change who may read a document ('everyone' or 'managers'); True if it existed."""
        if visibility not in VISIBILITIES:
            raise KnowledgeError("Visibility must be 'everyone' or 'managers'.")
        return self.repo.set_knowledge_visibility(doc_id, visibility)

    def documents(self, include_manager_only: bool = True) -> List[Dict[str, Any]]:
        """Documents without their text; ``include_manager_only=False`` hides the managers-only ones."""
        return self.repo.get_knowledge_docs(include_manager_only)

    # ------------------------------------------------------------------ search
    def _index(self, include_manager_only):
        signature = self.repo.knowledge_signature(include_manager_only)
        cached = self._cache.get(include_manager_only)
        if cached and cached[0] == signature:
            return cached[1]
        chunks = []
        for doc in self.repo.get_knowledge_docs(include_manager_only, with_content=True):
            chunks += split_document(doc["id"], doc["filename"], doc["content"])
        index = BM25Index(chunks)
        self._cache[include_manager_only] = (signature, index)
        return index

    def search(self, question: str, is_manager: bool, k: int = 3) -> list:
        """The passages that answer ``question`` for this kind of user (``[]`` if none do)."""
        hits = self._index(bool(is_manager)).search(question, k)
        out, used = [], 0
        for hit in hits:
            text = hit.text if len(hit.text) <= PASSAGE_CHARS else hit.text[:PASSAGE_CHARS].rsplit(" ", 1)[0] + " …"
            if out and used + len(text) > TOTAL_CHARS:
                break
            out.append(hit._replace(text=text))
            used += len(text)
        return out


def sources_of(hits) -> List[str]:
    """File names of the hits, each once, in ranking order."""
    return list(dict.fromkeys(h.filename for h in hits))


def format_passages(hits) -> str:
    """The passages as text for a reply that quotes them (used when no model is available)."""
    parts = ["Here is what the documents say:"]
    for hit in hits:
        where = hit.filename + (" — " + hit.heading if hit.heading else "")
        parts.append("From %s:\n%s" % (where, hit.text))
    parts.append("Sources: " + ", ".join(sources_of(hits)))
    return "\n\n".join(parts)
