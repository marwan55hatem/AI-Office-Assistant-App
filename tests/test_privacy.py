"""Employees can never reach team data; the model and the documents are walled off too."""

import json

import pytest

from assistant.answers import AssistantEngine
from chat.backend_local import LocalBackend

TEAM_QUESTIONS = [
    "How is the team doing today?",
    "Who is the best performer?",
    "Who should I check in on?",
    "Summarize last week's performance",
    "who is working right now",
]


@pytest.fixture
def team(db, marwan, make_employee, add_session):
    """Marwan plus two colleagues with distinctive names and numbers."""
    sara = make_employee("sara", "Sara Qwerty")
    omar = make_employee("omar", "Omar Zxcvb")
    add_session(marwan["id"], focus=3000, distraction=100)
    add_session(sara["id"], focus=1800, distraction=4200)
    add_session(omar["id"], days_ago=9, focus=3600)
    return {"sara": sara, "omar": omar}


@pytest.mark.parametrize("question", TEAM_QUESTIONS)
def test_an_employee_gets_a_refusal_with_no_names_or_numbers(chatter, marwan, team, question):
    reply = chatter(marwan).ask(question)
    assert reply.intent == "denied" and reply.kind == "text"
    assert "only available to managers" in reply.full_text
    for secret in ("Sara", "Omar", "Qwerty", "Zxcvb", "4200", "1h"):
        assert secret not in reply.full_text


def test_the_engine_never_loads_other_people_for_an_employee(db, marwan, team, monkeypatch):
    engine = AssistantEngine(db, marwan["id"])

    def forbidden():
        raise AssertionError("an employee's engine asked for the employee list")

    monkeypatch.setattr(engine, "_employees", forbidden)
    for question in TEAM_QUESTIONS:
        assert engine.ask(question, {}).intent == "denied"


def test_the_same_questions_work_for_a_manager(chatter, manager, team):
    reply = chatter(manager).ask("Who should I check in on?")
    assert reply.intent == "check_in" and "Sara Qwerty" in reply.full_text


def test_an_employee_cannot_ask_about_a_colleague_by_name(chatter, marwan, team):
    reply = chatter(marwan).ask("How is Sara Qwerty doing?")
    assert "Sara" not in reply.full_text or "only available to managers" in reply.full_text


def test_the_model_prompt_never_contains_database_content(db, marwan, manager, team, chatter):
    db.add_task(marwan["id"], "Secret merger plan", assigned_by=manager["id"], description="Confidential details")
    private = ["Secret merger plan", "Confidential details", "Sara Qwerty", "Omar Zxcvb", "Marwan Hatem", "Admin Manager"]
    for user in (marwan, manager):
        c = chatter(user)
        c.ask("what tasks do i have" if user is marwan else "How is the team doing today?")   # data-bearing engine turn first
        for question in ("How do I build a CNN model?", "what is overfitting", "explain RAG"):
            reply = c.ask(question)
            assert reply.kind == "llm"
            blob = json.dumps(reply.messages, ensure_ascii=False)
            assert not [p for p in private if p in blob], (user["username"], question)


def test_engine_answers_are_never_fed_back_to_the_model(db, marwan, manager, chatter):
    db.add_task(marwan["id"], "Secret merger plan", assigned_by=manager["id"])
    c = chatter(marwan)
    c.ask("what tasks do i have")                       # stored with source 'engine'
    c.ask("What is overfitting?", answer="Memorising.")  # stored with source 'llm'
    reply = c.ask("and how do I prevent it?")
    assert "Secret merger plan" not in json.dumps(reply.messages)
    assert len(reply.messages) == 4                      # system, question, answer, new question


def test_manager_only_documents_are_invisible_to_employees(db, marwan, manager, chatter):
    from knowledge.store import KnowledgeBase
    kb = KnowledgeBase(db)
    kb.add_text("salary.md", "# Salary bands\n\nA senior engineer is level L5 with bonus 1.4.", "managers", manager["id"])
    kb.add_text("policy.md", "# Expenses\n\nTravel claims within 14 days.", "everyone", manager["id"])
    question = "What is the salary band of a senior engineer?"
    employee_reply = chatter(marwan).ask(question)
    assert employee_reply.sources == [] and "L5" not in json.dumps(employee_reply.messages)
    manager_reply = chatter(manager).ask(question)
    assert manager_reply.sources == ["salary.md"] and "L5" in manager_reply.messages[-1]["content"]
    assert chatter(marwan).ask("How many days for travel claims?").sources == ["policy.md"]


def test_without_a_model_an_employee_still_gets_no_manager_only_text(db, marwan, manager, chatter):
    from knowledge.store import KnowledgeBase
    KnowledgeBase(db).add_text("salary.md", "# Salary\n\nLevel L5 bonus 1.4 for senior engineers.", "managers", manager["id"])
    reply = chatter(marwan, model_present=False).ask("salary of senior engineers level")
    assert "L5" not in reply.full_text


def test_a_user_cannot_touch_somebody_elses_chat(db, marwan, manager):
    mine = LocalBackend(db, marwan["id"])
    chat_id = mine.new_chat().id
    mine.send_message(chat_id, "private question")
    theirs = LocalBackend(db, manager["id"])
    for action in (lambda: theirs.get_messages(chat_id), lambda: theirs.send_message(chat_id, "hi"),
                   lambda: theirs.delete_chat(chat_id), lambda: theirs.rename_chat(chat_id, "x")):
        with pytest.raises(PermissionError):
            action()
    assert [c.id for c in theirs.list_chats()] == []


def test_a_repository_exposes_only_its_own_methods(db):
    """Interface segregation doubles as access control: the chat repository cannot delete users."""
    assert hasattr(db.chats, "add_ai_message")
    with pytest.raises(AttributeError):
        db.chats.delete_user_cascade
    with pytest.raises(AttributeError):
        db.knowledge.get_user
