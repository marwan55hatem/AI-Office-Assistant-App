"""/users, /invites and /company: the manager's account administration.

Every lookup goes through a repository bound to the caller's company, so an id that
belongs to another company is simply "not found" (404), never "forbidden".
"""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.core import security
from app.core.config import get_settings
from app.core.deps import CurrentManager, CurrentUser
from app.db.models import Company, User
from app.repositories.tenant import CompanyRepository, InviteRepository, RefreshTokenRepository, UserRepository
from app.schemas.auth import CompanyOut, InviteCreate, InviteOut, UserOut, UserStatusChange
from app.services.auth_service import _join_code

router = APIRouter(tags=["people"])
NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.get("/users", response_model=list[UserOut])
def list_users(principal: CurrentManager,
               status_filter: Literal["pending", "active", "disabled"] | None = Query(None, alias="status"),
               limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    users = UserRepository(principal.session, principal.company_id)
    conditions = [User.status == status_filter] if status_filter else []
    return users.list(*conditions, order_by=User.created_at, limit=limit, offset=offset)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, principal: CurrentUser):
    if not principal.is_manager and user_id != principal.user.id:
        raise NOT_FOUND                       # employees see only themselves
    user = UserRepository(principal.session, principal.company_id).get(user_id)
    if user is None:
        raise NOT_FOUND
    return user


@router.post("/users/{user_id}/approve", response_model=UserOut)
def approve_user(user_id: uuid.UUID, principal: CurrentManager):
    users = UserRepository(principal.session, principal.company_id)
    user = users.get(user_id)
    if user is None:
        raise NOT_FOUND
    if user.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a pending account can be approved")
    return users.update(user, status="active")


@router.patch("/users/{user_id}/status", response_model=UserOut)
def set_user_status(user_id: uuid.UUID, body: UserStatusChange, principal: CurrentManager):
    users = UserRepository(principal.session, principal.company_id)
    user = users.get(user_id)
    if user is None:
        raise NOT_FOUND
    if user.id == principal.user.id and body.status == "disabled":
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot disable your own account")
    users.update(user, status=body.status)
    if body.status == "disabled":
        RefreshTokenRepository(principal.session, principal.company_id).revoke_all_for_user(user.id)
    return user


@router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(body: InviteCreate, principal: CurrentManager):
    token = security.new_token()
    invite = InviteRepository(principal.session, principal.company_id).add(
        email=body.email, token_hash=security.sha256(token), created_by=principal.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().invite_days))
    return InviteOut(id=invite.id, email=invite.email, expires_at=invite.expires_at, token=token)


@router.get("/invites", response_model=list[InviteOut])
def list_invites(principal: CurrentManager):
    invites = InviteRepository(principal.session, principal.company_id).list(order_by=InviteRepository.model.created_at)
    return [InviteOut(id=i.id, email=i.email, expires_at=i.expires_at) for i in invites if i.used_at is None]


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(invite_id: uuid.UUID, principal: CurrentManager):
    invites = InviteRepository(principal.session, principal.company_id)
    invite = invites.get(invite_id)
    if invite is None:
        raise NOT_FOUND
    invites.delete(invite)


@router.get("/company", response_model=CompanyOut)
def get_company(principal: CurrentManager):
    return CompanyRepository(principal.session, principal.company_id).get()


@router.post("/company/join-code", response_model=CompanyOut)
def rotate_join_code(principal: CurrentManager):
    """Issue a new join code (e.g. after the old one was shared too widely)."""
    company: Company = CompanyRepository(principal.session, principal.company_id).get()
    company.join_code = _join_code()
    principal.session.flush()
    return company
