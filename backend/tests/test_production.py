"""Phase 9: production readiness -- health endpoints and the production configuration guard."""
from pydantic import SecretStr

from app.core.config import get_settings
from app.main import production_problems


def test_health_and_readiness(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok", "database": "ok"}


def test_readiness_reports_a_database_outage(client, monkeypatch):
    from app.db import session

    class Down:
        def connect(self):
            raise OSError("connection refused")

    monkeypatch.setattr(session, "get_engine", lambda: Down())
    response = client.get("/health/ready")
    assert response.status_code == 503 and response.json()["database"] == "down"


def production(**changes):
    base = get_settings().model_copy(update={
        "environment": "production", "app_link_url": "https://office.example.com",
        "cors_origins": ["https://office.example.com"], "email_provider": "resend",
        "groq_api_key": SecretStr("gsk_x"), "web_proxy_secret": SecretStr("s" * 40), "allow_rls_bypass": False})
    return base.model_copy(update=changes)


def test_a_good_production_configuration_passes():
    assert production_problems(production()) == ([], [])


def test_unsafe_production_settings_stop_the_start():
    errors, _ = production_problems(production(app_link_url="http://office.example.com",
                                               cors_origins=["http://localhost:3000"], allow_rls_bypass=True))
    assert len(errors) == 3


def test_missing_optional_services_are_warnings():
    _, warnings = production_problems(production(email_provider="console", groq_api_key=None, web_proxy_secret=None))
    assert len(warnings) == 3


def test_development_is_not_checked():
    assert production_problems(get_settings()) == ([], [])


def _start_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "start.py"
    spec = importlib.util.spec_from_file_location("start_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_app_link_is_derived_from_the_owner_link():
    env = {"MIGRATIONS_DATABASE_URL": "postgresql://owner:o-pw@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require",
           "APP_ROLE_PASSWORD": "a/b+c=d@e"}
    _start_module().prepare_database_urls(env)
    assert env["MIGRATIONS_DATABASE_URL"].startswith("postgresql+psycopg://owner:o-pw@ep-x.")
    assert env["DATABASE_URL"] == ("postgresql+psycopg://office_app:a%2Fb%2Bc%3Dd%40e"
                                   "@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require")


def test_an_explicit_app_link_is_kept():
    env = {"MIGRATIONS_DATABASE_URL": "postgres://owner:pw@h/db", "APP_ROLE_PASSWORD": "x",
           "DATABASE_URL": "postgres://office_app:other@h2/db"}
    _start_module().prepare_database_urls(env)
    assert env["DATABASE_URL"] == "postgresql+psycopg://office_app:other@h2/db"
    assert env["MIGRATIONS_DATABASE_URL"] == "postgresql+psycopg://owner:pw@h/db"
