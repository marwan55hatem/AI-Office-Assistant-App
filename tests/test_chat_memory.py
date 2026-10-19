"""Chat persistence, titles, the model's memory and "what did I just say?"."""

import pytest

from chat.backend_local import LocalBackend
from llm.prompts import STOPPED_MARK, build_messages, clean_reply, with_sources


@pytest.fixture
def backend(db, marwan):
    return LocalBackend(db, marwan["id"])


def test_messages_are_stored_in_order_and_survive_a_new_backend(db, marwan, backend):
    chat_id = backend.new_chat().id
    backend.send_message(chat_id, "first")
    backend.save_reply(chat_id, "answer one", "engine")
    backend.send_message(chat_id, "second")
    again = LocalBackend(db, marwan["id"])           # "restart": same database, new objects
    assert [(m.role, m.content) for m in again.get_messages(chat_id)] == [
        ("user", "first"), ("assistant", "answer one"), ("user", "second")]


def test_limit_returns_the_last_messages_in_order(backend):
    chat_id = backend.new_chat().id
    for number in range(5):
        backend.send_message(chat_id, "m%d" % number)
    assert [m.content for m in backend.get_messages(chat_id, limit=2)] == ["m3", "m4"]


def test_empty_message_is_refused(backend):
    chat_id = backend.new_chat().id
    with pytest.raises(ValueError):
        backend.send_message(chat_id, "   ")


def test_the_first_question_becomes_the_title(backend):
    chat_id = backend.new_chat().id
    backend.send_message(chat_id, "x" * 80)
    title = backend.auto_title(chat_id)
    assert title == "x" * 40 + "…"
    backend.send_message(chat_id, "another")
    assert backend.auto_title(chat_id) is None        # only the first time


def test_rename_and_blank_rename(backend):
    chat_id = backend.new_chat().id
    assert backend.rename_chat(chat_id, "My plan")[0]
    assert backend.list_chats()[0].title == "My plan"
    assert not backend.rename_chat(chat_id, "   ")[0]


def test_chats_are_listed_newest_activity_first(backend):
    first, second = backend.new_chat().id, backend.new_chat().id
    backend.db.conn.execute("UPDATE ai_chats SET updated_at = '2020-01-01 00:00:00' WHERE id = ?", (first,))
    backend.db.conn.commit()
    backend.send_message(second, "hi")
    assert [c.id for c in backend.list_chats()] == [second, first]


def test_deleting_a_chat_deletes_its_messages(db, backend):
    chat_id = backend.new_chat().id
    backend.send_message(chat_id, "hello")
    assert backend.delete_chat(chat_id)[0]
    assert db.count_ai_messages(chat_id) == 0 and backend.list_chats() == []


def test_each_stored_reply_remembers_who_wrote_it(backend):
    chat_id = backend.new_chat().id
    backend.send_message(chat_id, "q")
    backend.save_reply(chat_id, "from the database", "engine")
    backend.send_message(chat_id, "q2")
    backend.save_reply(chat_id, "from the model", "llm")
    assert [m.source for m in backend.get_messages(chat_id)] == ["", "engine", "", "llm"]


def test_the_models_memory_is_limited_to_six_pairs(chatter, marwan):
    c = chatter(marwan)
    for number in range(9):
        c.ask("Explain topic number %d" % number, answer="Answer %d" % number)
    reply = c.ask("one more question")
    assert len(reply.messages) == 1 + 2 * 6 + 1
    assert reply.messages[1]["content"] == "Explain topic number 3"


def test_clean_reply_removes_the_marks_the_app_added():
    text = with_sources("Use dropout." + STOPPED_MARK, ["a.md"])
    assert clean_reply("Use dropout." + STOPPED_MARK) == "Use dropout."
    assert clean_reply(with_sources("Use dropout.", ["a.md", "b.md"])) == "Use dropout."
    assert clean_reply("Sources: are important\nmore") == "Sources: are important\nmore"
    assert text.endswith("Sources: a.md")


def test_build_messages_puts_documents_in_the_last_question_only():
    class Hit:
        filename, heading, text = "cnn.md", "Pooling", "Max pooling keeps the largest value."

    messages = build_messages([("old question", "old answer")], "What is pooling?", [Hit()])
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert "Max pooling" in messages[-1]["content"] and "cnn.md" in messages[-1]["content"]
    assert "Max pooling" not in messages[1]["content"] + messages[2]["content"]


def test_what_did_i_just_say_is_answered_from_this_chat(chatter, marwan):
    c = chatter(marwan)
    c.ask("What tasks do I have?")
    reply = c.ask("what did I just ask?")
    assert reply.intent == "recall" and "What tasks do I have?" in reply.full_text


def test_recall_at_the_start_of_a_chat(chatter, marwan):
    reply = chatter(marwan).ask("what did i just say")
    assert reply.intent == "recall" and "start of our conversation" in reply.full_text
