"""A tiny, safe Markdown subset for chat replies.  Qt-free.

What the small language model writes is cut into **text** and **code** parts:

* code is whatever sits between ``` fences (an unfinished fence -- the reply is still
  being written -- counts as code that is not closed yet);
* text becomes HTML for a ``QLabel``: ``**bold**``, ``# headings``, ``- bullets`` and
  ```inline code```.  Everything else is escaped first, so a reply (or a document
  passage) containing ``<b>`` or ``<script>`` is shown as text and never interpreted.
"""

import html
import re
from collections import namedtuple

Segment = namedtuple("Segment", "kind text lang closed")     # kind: "text" | "code"

_FENCE = re.compile(r"^\s*```\s*([\w+#.\-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
MONO = "font-family:Consolas,'Cascadia Mono','Courier New',monospace;"


def split_segments(text):
    """``[Segment]``: the reply as alternating text and code parts, in order."""
    segments, buffer, in_code, lang = [], [], False, ""

    def flush_text():
        body = "\n".join(buffer).strip("\n")
        if body.strip():
            segments.append(Segment("text", body, "", True))
        buffer.clear()

    for line in str(text).replace("\r\n", "\n").split("\n"):
        match = _FENCE.match(line)
        if match and not in_code:
            flush_text()
            in_code, lang = True, match.group(1)
        elif match and in_code:
            segments.append(Segment("code", "\n".join(buffer).rstrip("\n"), lang, True))
            buffer.clear()
            in_code = False
        else:
            buffer.append(line)
    if in_code:
        segments.append(Segment("code", "\n".join(buffer).rstrip("\n"), lang, False))
    else:
        flush_text()
    return segments


def _inline(escaped):
    """Bold and inline code inside one already-escaped line."""
    out, position = [], 0
    for match in _INLINE_CODE.finditer(escaped):
        out.append(_BOLD.sub(r"<b>\1</b>", escaped[position:match.start()]))
        out.append('<span style="%s">%s</span>' % (MONO, match.group(1)))
        position = match.end()
    out.append(_BOLD.sub(r"<b>\1</b>", escaped[position:]))
    return "".join(out)


def to_html(text):
    """The text part of a reply as HTML (everything escaped, a few styles allowed)."""
    lines = []
    for line in str(text).split("\n"):
        stripped = line.lstrip(" ")
        indent = "&nbsp;" * (len(line) - len(stripped))
        escaped = html.escape(stripped, quote=False)
        heading, bullet = _HEADING.match(escaped), _BULLET.match(escaped)
        if heading:
            body = "<b>%s</b>" % _inline(heading.group(2))
        elif bullet:
            body = "•&nbsp;" + _inline(bullet.group(1))
        elif escaped.startswith("Sources:"):
            body = "<i>%s</i>" % _inline(escaped)
        else:
            body = _inline(escaped)
        lines.append(indent + body)
    return "<br>".join(lines)
