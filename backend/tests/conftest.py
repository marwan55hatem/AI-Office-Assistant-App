"""Test setup: a fresh PostgreSQL database, migrated with Alembic, used through a
restricted role so Row-Level Security is really in force during the tests.

Needs the local database from docker-compose.yml (``docker compose up -d db``) or
TEST_OWNER_URL pointing at any PostgreSQL where that user may create databases/roles.
"""
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
OWNER_URL = os.environ.get(
    "TEST_OWNER_URL", "postgresql+psycopg://office_owner:dev-owner-password@localhost:55432/office")
TEST_DB = "office_test"
TEST_ROLE = "office_app_test"
TEST_ROLE_PASSWORD = secrets.token_urlsafe(18)

owner_test_url = make_url(OWNER_URL).set(database=TEST_DB)
app_test_url = owner_test_url.set(username=TEST_ROLE, password=TEST_ROLE_PASSWORD)

# Settings are read once, so they must be in the environment before the app is imported.
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": app_test_url.render_as_string(hide_password=False),
    "MIGRATIONS_DATABASE_URL": owner_test_url.render_as_string(hide_password=False),
    "JWT_SECRET": secrets.token_urlsafe(48),
    "CORS_ORIGINS": '["http://localhost:3000"]',
    # The tests must never reach the real model or spend tokens, even when backend/.env holds a
    # real key: environment variables win over .env, and an empty key means "no model set up".
    "GROQ_API_KEY": "",
    "AI_FAKE_MODEL": "0",
})


def _create_test_database() -> None:
    admin = create_engine(OWNER_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        connection.execute(text(f"CREATE DATABASE {TEST_DB}"))
    admin.dispose()


def _migrate_and_grant() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.attributes["url"] = os.environ["MIGRATIONS_DATABASE_URL"]
    command.upgrade(config, "head")
    env = {**os.environ, "APP_ROLE_NAME": TEST_ROLE, "APP_ROLE_PASSWORD": TEST_ROLE_PASSWORD}
    result = subprocess.run([sys.executable, str(BACKEND / "scripts" / "create_app_role.py")],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="session", autouse=True)
def database():
    _create_test_database()
    _migrate_and_grant()
    yield


@pytest.fixture(scope="session")
def owner_engine(database):
    engine = create_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean(owner_engine):
    """Every test starts with empty tables and fresh rate-limit counters."""
    from app.core.ratelimit import login_limiter
    from app.db.models import TENANT_TABLES

    with owner_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(TENANT_TABLES)}, companies CASCADE"))
    login_limiter.reset()
    from app.services.report_cache import report_cache
    report_cache.clear()
    yield


@pytest.fixture(scope="session")
def client(database):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


# ---------------------------------------------------------------- helpers
PASSWORD = "correct horse battery"


def register(client, company="Acme", email="boss@acme-corp.com", name="Boss"):
    response = client.post("/auth/register-company", json={
        "company_name": company, "owner_name": name, "email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()


def auth(tokens) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def join_with_code(client, manager_tokens, email, name="Worker"):
    code = client.get("/company", headers=auth(manager_tokens)).json()["join_code"]
    response = client.post("/auth/join", json={
        "full_name": name, "email": email, "password": PASSWORD, "company_code": code})
    assert response.status_code == 201, response.text
    return code


def add_active_employee(client, manager_tokens, email, name="Worker"):
    """Join with the company code, get approved, sign in; returns (tokens, user_id)."""
    join_with_code(client, manager_tokens, email, name)
    pending = client.get("/users", params={"status": "pending"}, headers=auth(manager_tokens)).json()
    user_id = next(u["id"] for u in pending if u["email"] == email)
    assert client.post(f"/users/{user_id}/approve", headers=auth(manager_tokens)).status_code == 200
    response = login(client, email)
    assert response.status_code == 200, response.text
    return response.json(), user_id
