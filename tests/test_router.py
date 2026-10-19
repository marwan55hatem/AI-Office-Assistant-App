"""Which questions go to the exact engine and which to the language model."""

import pytest


@pytest.fixture
def employee(db, marwan, manager):
    """Marwan with two open tasks, one of them with a description."""
    db.add_task(marwan["id"], "Prepare Q3 report", assigned_by=manager["id"], description="Numbers are on the drive.")
    db.add_task(marwan["id"], "Buy milk")
    return marwan


@pytest.mark.parametrize("question", [
    "How do I build a CNN model?",
    "What is overfitting?",
    "What is dropout?",
    "How does backpropagation work?",
    "Explain transformers in simple words",
    "write a python function to reverse a string",
    "Who is the president of France?",
])
def test_general_questions_go_to_the_language_model(chatter, employee, question):
    reply = chatter(employee).ask(question)
    assert reply.kind == "llm" and reply.source == "llm"
    assert reply.messages[-1]["role"] == "user" and reply.messages[-1]["content"] == question


@pytest.mark.parametrize("question, intent", [
    ("What tasks do I have?", "list_tasks"),
    ("What's due soon?", "task_deadlines"),
    ("what should i do first", "task_next"),
    ("hello", "greeting"),
    ("thanks", "thanks"),
    ("what can you do", "capabilities"),
])
def test_questions_about_your_own_data_stay_with_the_engine(chatter, employee, question, intent):
    reply = chatter(employee).ask(question)
    assert reply.kind == "text" and reply.source == "engine" and reply.intent == intent


def test_a_named_task_gets_its_plan_from_the_engine(chatter, employee):
    reply = chatter(employee).ask("How should I start on the Q3 report?")
    assert reply.kind == "text" and reply.intent == "task_howto"
    assert "Prepare Q3 report" in reply.full_text and "Numbers are on the drive" in reply.full_text


def test_a_howto_about_an_unrelated_topic_is_not_mistaken_for_a_task(db, make_employee, manager, chatter):
    """A user with ONE task must not get that task's plan for 'how to build a CNN'."""
    solo = make_employee("solo", "Solo Worker")
    db.add_task(solo["id"], "Only task", assigned_by=manager["id"])
    reply = chatter(solo).ask("how to build a cnn model")
    assert reply.kind == "llm"
    assert "Only task" not in str(reply.messages)


def test_a_bare_howto_still_means_the_single_task(db, make_employee, manager, chatter):
    solo = make_employee("solo", "Solo Worker")
    db.add_task(solo["id"], "Only task", assigned_by=manager["id"])
    reply = chatter(solo).ask("how do i start")
    assert reply.kind == "text" and "Only task" in reply.full_text


def test_a_weak_follow_up_after_a_model_answer_goes_to_the_model(chatter, employee):
    c = chatter(employee)
    c.ask("What is overfitting?", answer="Memorising the training data.")
    follow_up = c.ask("and how can I prevent it?")
    assert follow_up.kind == "llm"
    assert [m["content"] for m in follow_up.messages[1:3]] == ["What is overfitting?", "Memorising the training data."]


def test_without_the_model_the_engine_answers_honestly(chatter, employee):
    reply = chatter(employee, model_present=False).ask("How do I build a CNN model?")
    assert reply.kind == "text" and "not sure" in reply.full_text.lower()


def test_switching_the_model_off_sends_everything_to_the_engine(chatter, employee):
    c = chatter(employee)
    c.backend.llm_enabled = False
    assert c.ask("What is dropout?").kind == "text"


def test_a_manager_question_about_the_team_is_answered_from_the_database(db, manager, marwan, add_session, chatter):
    add_session(marwan["id"], focus=3600)
    reply = chatter(manager).ask("How is the team doing today?")
    assert reply.kind == "text" and reply.intent == "team_status" and "Marwan Hatem" in reply.full_text


def test_a_manager_asking_something_general_also_gets_the_model(chatter, manager):
    assert chatter(manager).ask("What is the difference between precision and recall?").kind == "llm"
