"""Small helpers shared by the data routers."""
import uuid

from fastapi import HTTPException, status

from app.core.deps import Principal
from app.db.models import User
from app.repositories.tenant import UserRepository

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
MANAGERS_ONLY = HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can do this")


def target_user(principal: Principal, user_id: uuid.UUID | None) -> User:
    """The user a request is about: yourself, or (managers only) anyone in the company.

    An employee asking about someone else gets 404, the same answer as an id from
    another company, so ids cannot be probed.
    """
    if user_id is None or user_id == principal.user.id:
        return principal.user
    if not principal.is_manager:
        raise NOT_FOUND
    user = UserRepository(principal.session, principal.company_id).get(user_id)
    if user is None:
        raise NOT_FOUND
    return user


def user_names(principal: Principal) -> dict[uuid.UUID, User]:
    return {u.id: u for u in UserRepository(principal.session, principal.company_id).list()}
