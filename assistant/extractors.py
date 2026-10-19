"""Plain-text extraction for uploaded documents."""

import logging
import os

logger = logging.getLogger(__name__)


def extract_text(path: str) -> str:
    """Return the plain-text contents of a .txt or .pdf file.

    Raises ValueError for unsupported extensions and RuntimeError when the file
    cannot be read.  An empty file simply returns ``""`` - the caller decides
    whether that is an error.
    """
    extension = os.path.splitext(path)[1].lower()

    if extension == ".txt":
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                return handle.read()
        except OSError as error:
            raise RuntimeError(f"Could not read {os.path.basename(path)}: {error}")

    if extension == ".pdf":
        fitz = _import_pymupdf()
        try:
            with fitz.open(path) as document:
                return "\n\n".join(page.get_text() for page in document)
        except Exception as error:
            raise RuntimeError(
                f"Could not read {os.path.basename(path)}: "
                f"{type(error).__name__}: {error}"
            )

    raise ValueError(f"Unsupported file: {extension}")


def _import_pymupdf():
    """Import PyMuPDF under either of its names.

    Recent releases renamed the module to ``pymupdf`` and printing a deprecation
    warning for ``import fitz``, so prefer the new name and fall back for older
    installations.
    """
    try:
        import pymupdf

        return pymupdf
    except Exception:
        logger.debug("PyMuPDF is not available", exc_info=True)
    try:
        import fitz

        return fitz
    except Exception as error:
        raise RuntimeError(
            f"PyMuPDF is not installed ({type(error).__name__}: {error}). "
            f"Install it with:  pip install PyMuPDF"
        )
