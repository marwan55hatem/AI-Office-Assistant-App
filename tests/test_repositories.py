"""The narrow repositories (interface segregation) and the backend contract (Liskov)."""

import inspect

import pytest

from chat.backend_base import BackendUnavailable, ChatBackend
from chat.backend_cloud import CloudBackend
from chat.backend_local import LocalBackend
from chat.chat_client import ChatClient
from database.db_manager import DatabaseManager
from database.repositories import REPOSITORIES

INFRASTRUCTURE = {"create_tables", "seed_demo_users", "close"}      # not part of any domain


def public_methods():
    return {name for name, member in inspect.getmembers(DatabaseManager, inspect.isfunction)
            if not name.startswith("_")} - INFRASTRUCTURE


def test_every_database_method_belongs_to_exactly_one_repository():
    owners = {}
    for attribute, repository in REPOSITORIES.items():
        for method in repository.METHODS:
            owners.setdefault(method, []).append(attribute)
    assert not {m: o for m, o in owners.items() if len(o) > 1}, "a method is listed twice"
    assert public_methods() - set(owners) == set(), "a DatabaseManager method has no repository"
    assert set(owners) - public_methods() == set(), "a repository lists a method that does not exist"


def test_repositories_forward_to_the_same_database(db, marwan):
    assert db.users.get_user("marwan", "1234", "employee")["id"] == marwan["id"]
    task_id = db.tasks.add_task(marwan["id"], "via repo")
    assert [t["id"] for t in db.get_tasks(marwan["id"])] == [task_id]


def test_a_repository_refuses_methods_of_other_domains(db):
    with pytest.raises(AttributeError, match="another repository"):
        db.tasks.create_ai_chat


def test_every_repository_is_attached_to_the_database(db):
    for attribute in REPOSITORIES:
        assert hasattr(db, attribute)


# ------------------------------------------------------------------ backend contract
ABSTRACT = {"list_chats", "new_chat", "delete_chat", "rename_chat", "get_messages",
            "send_message", "stream_reply", "save_reply", "auto_title"}


def test_the_contract_lists_every_operation_the_client_needs():
    assert set(ChatBackend.__abstractmethods__) == ABSTRACT


def test_the_local_backend_keeps_the_contract(db, marwan):
    backend = LocalBackend(db, marwan["id"])
    assert isinstance(backend, ChatBackend)
    assert ABSTRACT <= {name for name, _ in inspect.getmembers(backend, inspect.ismethod)}


def test_the_cloud_backend_refuses_to_be_created_instead_of_failing_later():
    with pytest.raises(BackendUnavailable):
        CloudBackend("https://example.invalid")


def test_the_client_falls_back_to_local_when_cloud_is_configured(db, marwan, monkeypatch):
    from chat import config
    monkeypatch.setattr(config, "BACKEND", "cloud")
    client = ChatClient(db, marwan["id"])
    assert isinstance(client.backend, LocalBackend)
    assert client.new_chat().title == "New Chat"


def test_a_backend_can_be_injected_into_the_client(db, marwan):
    sentinel = LocalBackend(db, marwan["id"])
    assert ChatClient(db, marwan["id"], backend=sentinel).backend is sentinel
