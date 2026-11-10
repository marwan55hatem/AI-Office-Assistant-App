"""FastAPI dependencies: the current user and a database session scoped to their company.

The company id and the role are taken from the verified access token only. The user
row is re-read on every request, so a disabled account or a changed role stops
working immediately and not only when the token expires.
"""
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import ACCESS, TokenError, decode_token
from app.db.models import User
from app.db.session import transaction
from app.repositories.tenant import UserRepository

_bearer = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in or the session expired",
                             headers={"WWW-Authenticate": "Bearer"})


@dataclass
class Principal:
    user: User
    company_id: uuid.UUID
    role: str
    session: Session

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"


def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Iterator[Principal]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UNAUTHORIZED
    try:
        claims = decode_token(credentials.credentials, ACCESS)
    except TokenError:
        raise UNAUTHORIZED from None
    with transaction(claims["cid"]) as session:
        user = UserRepository(session, claims["cid"]).get(claims["sub"])
        if user is None or user.status != "active" or user.role != claims.get("role"):
            raise UNAUTHORIZED
        yield Principal(user=user, company_id=claims["cid"], role=user.role, session=session)


def manager_principal(principal: Annotated[Principal, Depends(current_principal, scope="function")]) -> Principal:
    if not principal.is_manager:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can do this")
    return principal


def invalidate_reports_after_write(request: Request,
                                   credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]):
    """Router dependency: after a change that alters report numbers (tasks, people), forget
    the company's cached reports. Declared before ``current_principal`` so it runs *after*
    the request's transaction has been committed."""
    yield
    if request.method != "GET" and credentials is not None:
        try:
            claims = decode_token(credentials.credentials, ACCESS)
        except TokenError:
            return
        from app.services.report_cache import report_cache
        report_cache.invalidate(claims["cid"])


# scope="function": the request's transaction is committed *before* the response is sent.
# (FastAPI's default for dependencies with yield finishes them after the response, so a client
# could act on an answer -- "approved", "accepted" -- before the change was saved, and a request
# right after it would still see the old state.)
CurrentUser = Annotated[Principal, Depends(current_principal, scope="function")]
CurrentManager = Annotated[Principal, Depends(manager_principal, scope="function")]
