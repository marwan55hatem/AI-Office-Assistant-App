"""Company A can never read or write company B's data.

Three independent checks:
1. the API: every route, called by company A with company B's ids, finds nothing, and
   no response to A contains anything of B;
2. the repository layer alone (on the owner connection, where RLS does NOT apply);
3. PostgreSQL Row-Level Security alone (raw SQL as the app role, no repository).
"""
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import TENANT_TABLES
from app.repositories import tenant as repos
from app.repositories.base import TenantRepository
from tests.conftest import add_active_employee, auth, join_with_code, register


# ---------------------------------------------------------------- seeding
def seed_every_table(owner_engine, company_id, manager_id, employee_id) -> dict:
    """Give a company one row in every tenant table (owner connection, so RLS is bypassed)."""
    ids = {"session": uuid.uuid4(), "task": uuid.uuid4(), "calendar": uuid.uuid4(), "document": uuid.uuid4(),
           "meeting": uuid.uuid4(), "invite": uuid.uuid4(), "refresh": uuid.uuid4(), "chat": uuid.uuid4(),
           "manager_chat": uuid.uuid4()}
    # "today" is this computer's date, like the checks below use (the database's UTC date can differ near midnight)
    p = {"c": company_id, "m": manager_id, "e": employee_id, "app": f"App of {company_id}", "today": date.today(), **ids}
    statements = [
        "INSERT INTO sessions (id, company_id, user_id, local_date, started_at, last_seen_at, focus_seconds) "
        "VALUES (:session, :c, :e, :today, now(), now(), 600)",
        "INSERT INTO events (company_id, client_event_id, session_id, user_id, event_type, occurred_at, app_name) "
        "VALUES (:c, gen_random_uuid(), :session, :e, 'focus', now(), 'Code')",
        "INSERT INTO session_apps (company_id, session_id, user_id, app_name, category, seconds) "
        "VALUES (:c, :session, :e, :app, 'neutral', 500)",
        "INSERT INTO ai_chats (id, company_id, user_id, title) VALUES (:chat, :c, :e, 'secret chat')",
        "INSERT INTO ai_chats (id, company_id, user_id, title) VALUES (:manager_chat, :c, :m, 'secret manager chat')",
        "INSERT INTO ai_messages (company_id, chat_id, role, content) VALUES (:c, :chat, 'user', 'secret question')",
        "INSERT INTO tasks (id, company_id, user_id, assigned_by, title) VALUES (:task, :c, :e, :m, 'secret task')",
        "INSERT INTO calendar_events (id, company_id, title, event_date, created_by) "
        "VALUES (:calendar, :c, 'secret meeting', current_date, :m)",
        "INSERT INTO calendar_attendees (company_id, event_id, user_id) VALUES (:c, :calendar, :e)",
        "INSERT INTO documents (id, company_id, filename, content, uploaded_by) "
        "VALUES (:document, :c, 'policy.md', 'secret policy', :m)",
        "INSERT INTO ai_usage (company_id, day, requests) VALUES (:c, current_date, 1)",
        "INSERT INTO meeting_requests (id, company_id, requested_by, manager_id, topic, proposed_times) "
        "VALUES (:meeting, :c, :e, :m, 'secret topic', '[\"2026-12-01T10:00:00Z\"]')",
        "INSERT INTO messages (company_id, employee_id, sender_id, body) VALUES (:c, :e, :e, 'secret message')",
        "INSERT INTO notifications (company_id, user_id, kind, title) VALUES (:c, :e, 'task', 'secret note')",
        "INSERT INTO email_log (company_id, user_id, template) VALUES (:c, :e, 'task_assigned')",
        "INSERT INTO invites (id, company_id, token_hash, created_by, expires_at) "
        "VALUES (:invite, :c, md5(random()::text) || md5(random()::text), :m, now() + interval '1 day')",
        "INSERT INTO refresh_tokens (id, company_id, user_id, expires_at) VALUES (:refresh, :c, :e, now() + interval '1 day')",
        "INSERT INTO password_resets (id, company_id, user_id, token_hash, expires_at) "
        "VALUES (gen_random_uuid(), :c, :e, md5(random()::text) || md5(random()::text), now() + interval '1 hour')",
    ]
    with owner_engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), p)
    return ids


@pytest.fixture
def two_companies(client, owner_engine):
    world = {}
    for name in ("A", "B"):
        manager = register(client, company=f"Company {name}", email=f"boss@{name.lower()}-corp.com", name=f"Boss {name}")
        employee, employee_id = add_active_employee(client, manager, f"worker@{name.lower()}-corp.com", f"Worker {name}")
        join_with_code(client, manager, f"pending@{name.lower()}-corp.com", f"Pending {name}")
        me = client.get("/auth/me", headers=auth(manager)).json()
        company_id, manager_id = uuid.UUID(me["company"]["id"]), uuid.UUID(me["user"]["id"])
        ids = seed_every_table(owner_engine, company_id, manager_id, uuid.UUID(employee_id))
        pending_id = next(u["id"] for u in client.get("/users", params={"status": "pending"},
                                                      headers=auth(manager)).json())
        world[name] = {"manager": manager, "employee": employee, "company_id": company_id,
                       "manager_id": manager_id, "employee_id": uuid.UUID(employee_id),
                       "pending_id": uuid.UUID(pending_id), "join_code": me["company"]["join_code"], **ids}
    return world


def _secrets_of(b) -> list[str]:
    return [str(b["company_id"]), str(b["manager_id"]), str(b["employee_id"]), str(b["pending_id"]),
            b["join_code"], "@b-corp.com", "Company B", str(b["invite"]), str(b["session"]), str(b["task"]),
            str(b["calendar"]), str(b["document"]), str(b["chat"]), "Worker B", "Boss B", f"App of {b['company_id']}"]


# ---------------------------------------------------------------- 1. API
#: for each path parameter, which of company B's ids to try
PARAM_TARGETS = {
    "user_id": ["employee_id", "pending_id", "manager_id"], "invite_id": ["invite"], "session_id": ["session"],
    "task_id": ["task"], "event_id": ["calendar"], "chat_id": ["chat", "manager_chat"], "doc_id": ["document"],
}
#: query parameters a route needs before it can even look an id up
REQUIRED_QUERY = {"/reports/employee/{user_id}": {"start": "2000-01-01", "end": "2000-01-31"}}
#: a valid body for each write, so the request reaches the lookup (and is not just rejected as invalid)
BODIES = {
    ("PATCH", "/users/{user_id}/status"): {"status": "disabled"},
    ("PATCH", "/tasks/{task_id}/deadline"): {"deadline_date": "2030-01-01"},
    ("PATCH", "/calendar/{event_id}"): {"title": "hijacked"},
    ("PUT", "/calendar/{event_id}/attendees"): {"user_ids": []},
    ("PATCH", "/ai/chats/{chat_id}"): {"title": "hijacked"},
    ("POST", "/ai/chats/{chat_id}/messages"): {"role": "user", "content": "hijacked"},
    ("PATCH", "/documents/{doc_id}"): {"visibility": "everyone"},
}


def _routes(app):
    """Every API operation, read from the OpenAPI schema (FastAPI may wrap included
    routers, so walking ``app.routes`` can miss them)."""
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            yield method.upper(), path


def test_the_route_sweep_sees_the_whole_api(client):
    found = {f"{m} {p}" for m, p in _routes(client.app)}
    assert {"POST /auth/login", "GET /users", "POST /users/{user_id}/approve",
            "PATCH /users/{user_id}/status", "DELETE /invites/{invite_id}", "GET /company"} <= found


def test_every_route_with_an_id_hides_other_companies(client, two_companies):
    a, b = two_companies["A"], two_companies["B"]
    checked = 0
    for method, path in _routes(client.app):
        params = [name for name in PARAM_TARGETS if "{" + name + "}" in path]
        if not params:
            continue
        assert len(params) == 1, f"add the parameters of {path} to PARAM_TARGETS"
        for target in PARAM_TARGETS[params[0]]:
            url = path.replace("{" + params[0] + "}", str(b[target]))
            body = BODIES.get((method, path))
            for who in ("manager", "employee"):
                response = client.request(method, url, json=body, params=REQUIRED_QUERY.get(path),
                                          headers=auth(a[who]))
                assert response.status_code in (403, 404), f"{who} of A got {response.status_code} on {method} {url}"
                checked += 1
    assert checked >= 40
    # and nothing of B was changed by those attempts
    statuses = {u["email"]: u["status"] for u in client.get("/users", headers=auth(b["manager"])).json()}
    assert statuses == {"boss@b-corp.com": "active", "worker@b-corp.com": "active", "pending@b-corp.com": "pending"}


#: query parameters that make each list endpoint return as much as it can
WIDE_QUERY = {
    "/stats/today": {"day": str(date.today())},
    "/stats/range": {"start": "2000-01-01", "end": "2100-01-01"},
    "/tasks": {"everyone": "true"},
    "/documents": {"with_content": "true"},
    "/events/recent": {"limit": "200"},
    "/calendar": {"start": "2000-01-01", "end": "2100-01-01"},
    "/reports/overview": {"start": str(date.today() - timedelta(days=300)), "end": str(date.today()), "limit": "200"},
    "/reports/trends": {"start": str(date.today() - timedelta(days=300)), "end": str(date.today())},
}


def test_no_response_to_company_a_mentions_company_b(client, two_companies):
    a, b = two_companies["A"], two_companies["B"]
    checked = 0
    for method, path in _routes(client.app):
        if method != "GET" or "{" in path:
            continue
        for who in ("manager", "employee"):
            response = client.get(path, params=WIDE_QUERY.get(path), headers=auth(a[who]))
            if who == "manager":
                assert response.status_code == 200, f"GET {path} as manager: {response.status_code} {response.text}"
            checked += 1
            for secret in _secrets_of(b):
                assert secret not in response.text, f"GET {path} as {who} of A leaked {secret!r}"
    assert checked >= 20


def test_company_a_data_is_visible_to_a(client, two_companies):
    """The sweep above is only meaningful if A's own data does come back."""
    a = two_companies["A"]
    headers = auth(a["manager"])
    assert str(a["session"]) in client.get("/sessions", headers=headers).text
    assert str(a["task"]) in client.get("/tasks", params={"everyone": "true"}, headers=headers).text
    assert str(a["document"]) in client.get("/documents", headers=headers).text
    today = client.get("/stats/today", params={"day": str(date.today())}, headers=headers).json()
    assert today["totals"]["focus_seconds"] == 600


def test_list_endpoints_return_only_own_company(client, two_companies):
    a = two_companies["A"]
    emails = {u["email"] for u in client.get("/users", headers=auth(a["manager"])).json()}
    assert emails == {"boss@a-corp.com", "worker@a-corp.com", "pending@a-corp.com"}


def test_tokens_of_one_company_cannot_be_redirected_to_another(client, two_companies):
    import jwt
    a, b = two_companies["A"], two_companies["B"]
    claims = jwt.decode(a["manager"]["access_token"], options={"verify_signature": False})
    claims["cid"] = str(b["company_id"])          # without the server key this cannot be signed
    forged = jwt.encode(claims, "x" * 40, algorithm="HS256")
    assert client.get("/users", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    # a correctly signed token whose user does not belong to the claimed company is rejected too
    real = jwt.encode(claims, get_settings().jwt_secret, algorithm="HS256")
    assert client.get("/users", headers={"Authorization": f"Bearer {real}"}).status_code == 401


def test_invite_and_join_code_of_b_only_join_b(client, two_companies):
    a, b = two_companies["A"], two_companies["B"]
    response = client.post("/auth/join", json={"full_name": "X", "email": "x@x-corp.com",
                                               "password": "correct horse battery", "company_code": b["join_code"]})
    assert response.status_code == 201
    a_pending = {u["email"] for u in client.get("/users", params={"status": "pending"}, headers=auth(a["manager"])).json()}
    assert "x@x-corp.com" not in a_pending


# ---------------------------------------------------------------- 2. repositories alone
REPOSITORIES = [cls for cls in vars(repos).values()
                if isinstance(cls, type) and issubclass(cls, TenantRepository) and cls is not TenantRepository]


def test_every_tenant_table_has_a_repository():
    covered = {cls.model.__tablename__ for cls in REPOSITORIES} | {"calendar_attendees", "ai_usage"}
    assert covered == set(TENANT_TABLES)


@pytest.mark.parametrize("repo_class", REPOSITORIES, ids=lambda c: c.__name__)
def test_repository_filters_by_company_without_rls(repo_class, two_companies, owner_engine):
    a, b = two_companies["A"], two_companies["B"]
    with Session(owner_engine) as session:           # owner: RLS does not apply here
        rows = repo_class(session, a["company_id"]).list()
        assert rows, f"{repo_class.__name__} found nothing for A"
        assert all(row.company_id == a["company_id"] for row in rows)
        b_row = repo_class(session, b["company_id"]).list()[0]
        assert repo_class(session, a["company_id"]).get(b_row.id) is None
        with pytest.raises(PermissionError):
            repo_class(session, a["company_id"]).update(b_row)
        with pytest.raises(PermissionError):
            repo_class(session, a["company_id"]).delete(b_row)
        session.rollback()


def test_repository_refuses_to_write_for_another_company(two_companies, owner_engine):
    a, b = two_companies["A"], two_companies["B"]
    with Session(owner_engine) as session:
        with pytest.raises(PermissionError):
            repos.TaskRepository(session, a["company_id"]).add(company_id=b["company_id"], user_id=b["employee_id"],
                                                               title="x")
        session.rollback()


# ---------------------------------------------------------------- 3. RLS alone
@pytest.fixture(scope="module")
def app_engine():
    engine = create_engine(get_settings().database_url)
    yield engine
    engine.dispose()


def test_app_role_is_subject_to_rls(app_engine):
    with app_engine.connect() as connection:
        flags = connection.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
    assert flags == (False, False)


@pytest.mark.parametrize("table", TENANT_TABLES + ("companies",))
def test_rls_shows_only_the_current_company(table, two_companies, app_engine):
    a, b = two_companies["A"], two_companies["B"]
    column = "id" if table == "companies" else "company_id"
    with app_engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.company_id', :c, true)"), {"c": str(a["company_id"])})
        seen = set(connection.execute(text(f"SELECT DISTINCT {column} FROM {table}")).scalars())
        assert seen == {a["company_id"]}
        # even naming B explicitly finds nothing
        assert connection.execute(text(f"SELECT count(*) FROM {table} WHERE {column} = :b"),
                                  {"b": b["company_id"]}).scalar() == 0
    with app_engine.begin() as connection:            # no company set: nothing at all
        assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


@pytest.mark.parametrize("table", ["tasks", "messages", "notifications", "documents"])
def test_rls_blocks_writing_into_another_company(table, two_companies, app_engine):
    a, b = two_companies["A"], two_companies["B"]
    with app_engine.connect() as connection:
        connection.execute(text("SELECT set_config('app.company_id', :c, false)"), {"c": str(a["company_id"])})
        # updates and deletes of B's rows touch nothing
        assert connection.execute(text(f"UPDATE {table} SET company_id = company_id WHERE company_id = :b"),
                                  {"b": b["company_id"]}).rowcount == 0
        assert connection.execute(text(f"DELETE FROM {table} WHERE company_id = :b"),
                                  {"b": b["company_id"]}).rowcount == 0
        connection.rollback()
        insert = {
            "tasks": "INSERT INTO tasks (id, company_id, user_id, title) VALUES (gen_random_uuid(), :b, :u, 'x')",
            "messages": "INSERT INTO messages (company_id, employee_id, sender_id, body) VALUES (:b, :u, :u, 'x')",
            "notifications": "INSERT INTO notifications (company_id, user_id, kind, title) VALUES (:b, :u, 'k', 'x')",
            "documents": "INSERT INTO documents (id, company_id, filename, content) VALUES (gen_random_uuid(), :b, 'f', 'x')",
        }[table]
        with pytest.raises(DBAPIError, match="row-level security"):
            connection.execute(text(insert), {"b": b["company_id"], "u": b["employee_id"]})
        connection.rollback()


def test_rls_blocks_moving_a_row_to_another_company(two_companies, app_engine):
    a, b = two_companies["A"], two_companies["B"]
    with app_engine.connect() as connection:
        connection.execute(text("SELECT set_config('app.company_id', :c, false)"), {"c": str(a["company_id"])})
        with pytest.raises(DBAPIError):
            connection.execute(text("UPDATE notifications SET company_id = :b"), {"b": b["company_id"]})
        connection.rollback()


def test_lookup_functions_return_only_what_login_needs(two_companies, app_engine):
    with app_engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM auth_find_user('worker@b-corp.com')")).mappings().one()
        assert set(row) == {"id", "company_id", "password_hash", "role", "status"}
        # the functions do not open the tables themselves
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 0
