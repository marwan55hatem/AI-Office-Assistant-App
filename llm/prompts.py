"""What the language model is told.  Qt-free and database-free on purpose.

The model gets only: this fixed instruction, the earlier questions and answers of
the same chat that the *model itself* wrote, the new question and -- when the
knowledge base has something about it -- the matching document passages.  It is
never given tasks, calendar entries or team numbers (those are answered by the
engine from the database), so no private data can reach, or leak from, the model.
"""

from typing import Dict, List

SYSTEM_PROMPT = (
    "You are the AI assistant inside a desktop office app. Answer clearly and correctly, "
    "especially about machine learning, deep learning, programming and everyday work topics.\n"
    "- Be concise and well structured: short paragraphs or numbered steps.\n"
    "- Put code in fenced code blocks and make sure it is complete (include every import).\n"
    "- If you are not sure of something, say so instead of guessing. Never invent facts, "
    "numbers, names, links or quotes.\n"
    "- You cannot see the user's tasks, deadlines, calendar or team data. If asked about them, "
    "say the user can ask for example \"What tasks do I have?\".\n"
    "- Reply in the language of the user's question (English or Arabic)."
)

STOPPED_MARK = " … (stopped)"      # the chat screen appends this to a reply the user cut short
SOURCES_PREFIX = "\n\nSources: "         # added by the app (not the model) after an answer that used documents

DOCUMENT_INSTRUCTIONS = (
    "Answer the question using the document excerpts below. Mention the file name in square "
    "brackets, like [notes.md], when you use an excerpt. If the excerpts do not contain the "
    "answer, say so briefly and then answer from your general knowledge, making clear that "
    "this part is general knowledge."
)


def clean_reply(text: str) -> str:
    """A stored reply as the model should see it again: no "(stopped)" mark, no "Sources:" line."""
    text = str(text)
    if text.endswith(STOPPED_MARK):
        text = text[: -len(STOPPED_MARK)]
    cut = text.rfind(SOURCES_PREFIX)
    if cut != -1 and "\n" not in text[cut + len(SOURCES_PREFIX):]:
        text = text[:cut]
    return text


def with_sources(text: str, sources: List[str]) -> str:
    """The reply followed by the line naming the documents it was based on."""
    return str(text).rstrip() + SOURCES_PREFIX + ", ".join(sources) if sources else str(text)


def question_with_documents(question: str, hits) -> str:
    """The user turn of a question that has document passages: passages first, question last."""
    parts = [DOCUMENT_INSTRUCTIONS, ""]
    for number, hit in enumerate(hits, 1):
        where = hit.filename + (" — " + hit.heading if hit.heading else "")
        parts += ["[%d] %s" % (number, where), hit.text, ""]
    parts.append("Question: " + str(question))
    return "\n".join(parts)


def build_messages(pairs, question: str, hits=None) -> List[Dict[str, str]]:
    """Chat messages for the model: system prompt + ``[(question, answer), ...]`` + new question.

    ``hits`` are document passages (``knowledge.bm25.Hit``) that go into the new question.
    Earlier turns are kept as plain questions and answers, without their passages.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for asked, answered in pairs:
        messages.append({"role": "user", "content": str(asked)})
        messages.append({"role": "assistant", "content": clean_reply(answered)})
    messages.append({"role": "user", "content": question_with_documents(question, hits) if hits else str(question)})
    return messages
