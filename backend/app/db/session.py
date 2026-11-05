"""Engine, sessions and the tenant context used by Row-Level Security.

Each request runs in exactly one transaction. The company id from the access token is
set with ``set_config('app.company_id', ..., true)``, which is local to that
transaction, so it can never leak to the next request on a pooled connection. The RLS
policies compare every row's ``company_id`` with this setting.
"""
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def set_tenant(session: Session, company_id: uuid.UUID | None) -> None:
    """Point RLS at ``company_id`` for the rest of the current transaction."""
    session.execute(text("SELECT set_config('app.company_id', :cid, true)"),
                    {"cid": str(company_id) if company_id else ""})


@contextmanager
def transaction(company_id: uuid.UUID | None = None) -> Iterator[Session]:
    """One transaction, committed on success and rolled back on any error."""
    with _session_factory().begin() as session:
        set_tenant(session, company_id)
        yield session


def check_app_role() -> dict:
    """Return the app role's flags; RLS does not apply to a superuser or BYPASSRLS role."""
    with get_engine().connect() as connection:
        row = connection.execute(text(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
    return {"role": row.rolname, "superuser": row.rolsuper, "bypassrls": row.rolbypassrls}
