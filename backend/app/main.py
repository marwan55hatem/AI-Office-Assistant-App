"""The FastAPI application."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.session import check_app_role
from app.routers import (ai, auth, calendar, chat, content, emails, meeting_requests, notifications, people,
                         reports, sessions, stats, tasks)
from app.services.email.providers import get_provider
from app.services.email.worker import EmailWorker

logger = logging.getLogger("office.api")


def production_problems(settings) -> tuple[list[str], list[str]]:
    """``(errors, warnings)`` about a production configuration. Errors stop the start."""
    errors, warnings = [], []
    if settings.environment != "production":
        return errors, warnings
    if not settings.app_link_url.startswith("https://"):
        errors.append("APP_LINK_URL must be the website's https:// address")
    insecure = [o for o in settings.cors_origins if not o.startswith("https://")]
    if insecure:
        errors.append(f"CORS_ORIGINS must list https:// origins only (found {len(insecure)} other)")
    if settings.allow_rls_bypass:
        errors.append("ALLOW_RLS_BYPASS must be off in production")
    if settings.email_provider in ("off", "console"):
        warnings.append(f"EMAIL_PROVIDER is '{settings.email_provider}': no e-mail will be sent")
    if not settings.groq_api_key or not settings.groq_api_key.get_secret_value():
        warnings.append("GROQ_API_KEY is not set: AI Chat answers only from the app's own data")
    if not settings.web_proxy_secret:
        warnings.append("WEB_PROXY_SECRET is not set: sign-ins through the website share one rate limit")
    return errors, warnings


def _check_database_role() -> None:
    """Refuse to run on a connection that would ignore Row-Level Security."""
    settings = get_settings()
    role = check_app_role()
    if (role["superuser"] or role["bypassrls"]) and not settings.allow_rls_bypass:
        raise RuntimeError(
            f"The app database role '{role['role']}' bypasses Row-Level Security. "
            "Connect as the restricted role created by scripts/create_app_role.py.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_database_role()
    settings = get_settings()
    errors, warnings = production_problems(settings)
    for warning in warnings:
        logger.warning("configuration: %s", warning)
    if errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))
    provider = get_provider(settings)                 # fails early on a bad EMAIL_PROVIDER
    logger.info("e-mail provider: %s", provider.name)
    worker = None
    if settings.email_worker_enabled and settings.environment != "test":
        worker = EmailWorker(settings.email_poll_seconds)
        worker.start()
    yield
    if worker is not None:
        worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Office Assistant API", version="2.0.0-dev", lifespan=lifespan,
                  docs_url=None if settings.environment == "production" else "/docs",
                  redoc_url=None, openapi_url=None if settings.environment == "production" else "/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])
    app.include_router(auth.router)
    app.include_router(people.router)
    for module in (sessions, stats, tasks, calendar, content, ai, reports, emails, meeting_requests, notifications,
                   chat):
        app.include_router(module.router)

    @app.get("/health", tags=["health"])
    def health():
        """Liveness: the process answers."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready():
        """Readiness: the database answers too (used by the host's health check)."""
        from fastapi.responses import JSONResponse
        from sqlalchemy import text

        from app.db.session import get_engine
        try:
            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            logger.warning("readiness: the database did not answer")
            return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
        return {"status": "ok", "database": "ok"}

    return app


app = create_app()
