"""Settings, read from environment variables (and a local .env file in development).

Secrets (the JWT key, database passwords) are never written in code or committed:
see .env.example for the names.
"""
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field("development", description="development | test | production")

    #: The application's connection: a role WITHOUT superuser / BYPASSRLS, so that
    #: PostgreSQL Row-Level Security applies to every query it runs.
    database_url: str
    #: The owner's connection, used only by Alembic migrations.
    migrations_database_url: str | None = None

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    invite_days: int = 7

    #: The website origin allowed by CORS (the desktop app does not need CORS).
    cors_origins: list[str] = ["http://localhost:3000"]

    login_attempts_per_minute: int = 5
    login_attempts_per_ip_per_minute: int = 30

    # -- the online chat model (Groq). The key lives only in the server's environment.
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    ai_reasoning_effort: str | None = "low"
    ai_max_output_tokens: int = 1500
    #: tokens (prompt + answer) one company may use per UTC day
    ai_daily_token_budget: int = 100_000
    ai_requests_per_user_per_minute: int = 10
    ai_history_pairs: int = 6
    #: how long the provider may keep request logs (shown in the app's Settings)
    ai_provider_log_days: int = 30
    #: development only: answer with a fixed text instead of calling Groq (ignored in production)
    ai_fake_model: bool = False

    #: Development only: allow an app role that bypasses RLS (never in production).
    allow_rls_bypass: bool = False

    @field_validator("environment")
    @classmethod
    def _known_environment(cls, value: str) -> str:
        if value not in {"development", "test", "production"}:
            raise ValueError("environment must be development, test or production")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
