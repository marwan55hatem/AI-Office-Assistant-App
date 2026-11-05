"""The FastAPI application."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.session import check_app_role
from app.routers import auth, calendar, content, people, sessions, stats, tasks

logger = logging.getLogger("office.api")


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
    yield


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
    for module in (sessions, stats, tasks, calendar, content):
        app.include_router(module.router)

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
