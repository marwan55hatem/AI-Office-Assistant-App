"""Password hashing (Argon2id) and JSON Web Tokens.

Access tokens are short-lived and carry the user id, the company id and the role.
Refresh tokens are JWTs too, but each one has a ``jti`` stored (hashed) in the
``refresh_tokens`` table so it can be rotated, revoked and checked for reuse.
"""
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()
#: Hash of a random password, verified when the e-mail is unknown so a failed login
#: takes the same time whether or not the account exists.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

ACCESS = "access"
REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    """A random, URL-safe secret for invite links."""
    return secrets.token_urlsafe(32)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _encode(claims: dict, lifetime: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {**claims, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, company_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    return _encode({"sub": str(user_id), "cid": str(company_id), "role": role, "typ": ACCESS},
                   timedelta(minutes=settings.access_token_minutes))


def create_refresh_token(user_id: uuid.UUID, company_id: uuid.UUID, jti: uuid.UUID) -> str:
    settings = get_settings()
    return _encode({"sub": str(user_id), "cid": str(company_id), "jti": str(jti), "typ": REFRESH},
                   timedelta(days=settings.refresh_token_days))


class TokenError(Exception):
    """The token is missing, malformed, expired or of the wrong type."""


def decode_token(token: str, expected_type: str) -> dict:
    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
                            options={"require": ["exp", "iat", "sub", "cid", "typ"]})
    except jwt.PyJWTError as error:
        raise TokenError(str(error)) from None
    if claims.get("typ") != expected_type:
        raise TokenError("wrong token type")
    try:
        claims["sub"] = uuid.UUID(claims["sub"])
        claims["cid"] = uuid.UUID(claims["cid"])
        if expected_type == REFRESH:
            claims["jti"] = uuid.UUID(claims["jti"])
    except (KeyError, ValueError):
        raise TokenError("malformed token") from None
    return claims
