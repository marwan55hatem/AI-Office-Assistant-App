"""Accounts: company registration, login, token refresh with rotation, logout, joining."""
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.core import security
from app.core.config import get_settings
from app.db import models
from app.db.session import set_tenant, transaction
from app.repositories import tenant as repos


class AuthError(Exception):
    """A failure the client is told about. ``status`` is the HTTP status to use."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


GENERIC_LOGIN_ERROR = "Wrong e-mail or password"
_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _join_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def _issue_tokens(session, user: models.User) -> dict:
    settings = get_settings()
    jti = uuid.uuid4()
    repos.RefreshTokenRepository(session, user.company_id).add(
        id=jti, user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days))
    return {
        "access_token": security.create_access_token(user.id, user.company_id, user.role),
        "refresh_token": security.create_refresh_token(user.id, user.company_id, jti),
        "expires_in": settings.access_token_minutes * 60,
    }


def register_company(company_name: str, owner_name: str, email: str, password: str) -> dict:
    company_id = uuid.uuid4()
    password_hash = security.hash_password(password)
    try:
        with transaction(company_id) as session:
            if repos.email_taken(session, email):
                raise AuthError("This e-mail address is already registered", 409)
            for _ in range(5):                       # a join-code collision is very unlikely
                code = _join_code()
                if repos.find_company_by_code(session, code) is None:
                    break
            session.add(models.Company(id=company_id, name=company_name, join_code=code))
            session.flush()
            user = repos.UserRepository(session, company_id).add(
                email=email, full_name=owner_name, role="manager", status="active",
                password_hash=password_hash, last_login_at=datetime.now(UTC))
            return _issue_tokens(session, user)
    except IntegrityError:
        raise AuthError("This e-mail address is already registered", 409) from None


def login(email: str, password: str) -> dict:
    with transaction() as session:
        found = repos.find_login(session, email)
        if not security.verify_password(found.password_hash if found else None, password):
            raise AuthError(GENERIC_LOGIN_ERROR, 401)
        if found.status == "pending":
            raise AuthError("Your account is waiting for a manager's approval", 403)
        if found.status != "active":
            raise AuthError("This account is disabled", 403)
        set_tenant(session, found.company_id)
        users = repos.UserRepository(session, found.company_id)
        user = users.get(found.id)
        values = {"last_login_at": datetime.now(UTC)}
        if security.needs_rehash(user.password_hash):
            values["password_hash"] = security.hash_password(password)
        users.update(user, **values)
        return _issue_tokens(session, user)


def refresh(refresh_token: str) -> dict:
    """Rotate: the old refresh token is revoked and a new pair is issued. Presenting a token
    that was already rotated is treated as theft and revokes every token of that user; a
    token revoked by sign-out, a password change or disabling is simply refused."""
    try:
        claims = security.decode_token(refresh_token, security.REFRESH)
    except security.TokenError:
        raise AuthError("The session expired, please sign in again", 401) from None
    company_id, user_id, jti = claims["cid"], claims["sub"], claims["jti"]
    reused = False
    with transaction(company_id) as session:
        tokens = repos.RefreshTokenRepository(session, company_id)
        stored = tokens.get(jti)
        if stored is None or stored.user_id != user_id:
            raise AuthError("The session expired, please sign in again", 401)
        if stored.revoked_at is not None:
            if stored.replaced_by is not None:
                # a token that was already rotated is being used again: someone copied it
                tokens.revoke_all_for_user(user_id)  # committed below, then rejected
                reused = True
            else:
                raise AuthError("The session expired, please sign in again", 401)   # signed out
        else:
            user = repos.UserRepository(session, company_id).get(user_id)
            if user is None or user.status != "active" or stored.expires_at <= datetime.now(UTC):
                tokens.update(stored, revoked_at=datetime.now(UTC))
                raise AuthError("The session expired, please sign in again", 401)
            pair = _issue_tokens(session, user)
            new_jti = security.decode_token(pair["refresh_token"], security.REFRESH)["jti"]
            tokens.update(stored, revoked_at=datetime.now(UTC), replaced_by=new_jti)
            return pair
    if reused:
        raise AuthError("The session expired, please sign in again", 401)


def logout(refresh_token: str) -> None:
    try:
        claims = security.decode_token(refresh_token, security.REFRESH)
    except security.TokenError:
        return                                        # nothing to revoke
    with transaction(claims["cid"]) as session:
        tokens = repos.RefreshTokenRepository(session, claims["cid"])
        stored = tokens.get(claims["jti"])
        if stored is not None and stored.revoked_at is None:
            tokens.update(stored, revoked_at=datetime.now(UTC))


def join(full_name: str, email: str, password: str, invite_token: str | None, company_code: str | None) -> None:
    """Create a pending employee account; a manager must approve it before the first login."""
    password_hash = security.hash_password(password)
    try:
        with transaction() as session:
            invite = None
            if invite_token:
                invite = repos.find_invite(session, security.sha256(invite_token))
                if (invite is None or invite.used_at is not None
                        or invite.expires_at <= datetime.now(UTC)):
                    raise AuthError("This invite link is not valid or has expired", 400)
                if invite.email and invite.email.lower() != email.lower():
                    raise AuthError("This invite was sent to a different e-mail address", 400)
                company_id = invite.company_id
            else:
                company_id = repos.find_company_by_code(session, company_code)
                if company_id is None:
                    raise AuthError("No company has this code", 400)
            if repos.email_taken(session, email):
                raise AuthError("This e-mail address is already registered", 409)
            set_tenant(session, company_id)
            user = repos.UserRepository(session, company_id).add(
                email=email, full_name=full_name, role="employee", status="pending",
                password_hash=password_hash)
            if invite is not None:
                invites = repos.InviteRepository(session, company_id)
                invites.update(invites.get(invite.id), used_at=datetime.now(UTC), used_by=user.id)
    except IntegrityError:
        raise AuthError("This e-mail address is already registered", 409) from None


def change_password(session, user: models.User, current_password: str, new_password: str) -> dict:
    """Check the current password, store the new hash, sign out every other device and
    return a fresh token pair for this one."""
    if not security.verify_password(user.password_hash, current_password):
        raise AuthError("The current password is wrong", 400)
    if current_password == new_password:
        raise AuthError("The new password must be different", 400)
    repos.UserRepository(session, user.company_id).update(user, password_hash=security.hash_password(new_password))
    repos.RefreshTokenRepository(session, user.company_id).revoke_all_for_user(user.id)
    return _issue_tokens(session, user)
