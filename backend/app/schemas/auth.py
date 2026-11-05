"""Request and response bodies.

Request models forbid unknown fields, so a client cannot slip in ``company_id`` or
``role``: those come from the token only.
"""
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Password = Annotated[str, Field(min_length=8, max_length=128)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=16, pattern=r"^[A-Za-z0-9]+$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterCompany(Strict):
    company_name: Name
    owner_name: Name
    email: EmailStr
    password: Password


class Login(Strict):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]


class RefreshRequest(Strict):
    refresh_token: Annotated[str, Field(min_length=20, max_length=2000)]


class Join(Strict):
    """Join a company with an invite token or the company's join code."""
    full_name: Name
    email: EmailStr
    password: Password
    invite_token: Annotated[str, Field(min_length=20, max_length=200)] | None = None
    company_code: Code | None = None

    @model_validator(mode="after")
    def _one_way_to_join(self):
        if bool(self.invite_token) == bool(self.company_code):
            raise ValueError("give either invite_token or company_code")
        return self


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    created_at: datetime
    last_login_at: datetime | None = None


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    join_code: str | None = None


class MeOut(BaseModel):
    user: UserOut
    company: CompanyOut


class JoinResult(BaseModel):
    status: Literal["pending"] = "pending"
    message: str = "Your account was created and is waiting for a manager's approval."


class InviteCreate(Strict):
    email: EmailStr | None = None


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str | None
    expires_at: datetime
    #: shown once, when the invite is created; only its hash is stored
    token: str | None = None


class UserStatusChange(Strict):
    status: Literal["active", "disabled"]


class ProfileUpdate(Strict):
    full_name: Name


class PasswordChange(Strict):
    current_password: Annotated[str, Field(min_length=1, max_length=128)]
    new_password: Password
