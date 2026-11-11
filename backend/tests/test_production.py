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
