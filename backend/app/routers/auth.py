"""/auth: register a company, sign in, refresh, sign out, join a company."""
import hmac

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import get_settings
from app.core.deps import CurrentUser
from app.core.ratelimit import login_limiter
from app.repositories.tenant import CompanyRepository
from app.schemas.auth import (
    CompanyOut, Join, JoinResult, Login, MeOut, PasswordChange, PasswordForgot, PasswordReset, RefreshRequest,
    RegisterCompany, TokenPair, UserOut,
)
from app.services import auth_service
from app.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])

TOO_MANY = HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, please wait a minute",
                         headers={"Retry-After": "60"})


def _client_ip(request: Request) -> str:
    """The caller's IP for rate limits. The website calls the API from its own server, so it
    passes the visitor's IP in ``X-Client-IP``; that header is trusted only together with the
    shared ``WEB_PROXY_SECRET`` (anyone else could just make it up)."""
    secret = get_settings().web_proxy_secret
    forwarded = request.headers.get("x-client-ip", "").strip()
    given = request.headers.get("x-web-proxy-secret", "")
    if secret and forwarded and given and hmac.compare_digest(given.encode(), secret.get_secret_value().encode()):
        return forwarded[:64]
    return request.client.host if request.client else "unknown"


def _limit(request: Request, email: str, action: str) -> None:
    settings = get_settings()
    ip = _client_ip(request)
    if not login_limiter.hit(f"{action}:ip:{ip}", settings.login_attempts_per_ip_per_minute):
        raise TOO_MANY
    if not login_limiter.hit(f"{action}:email:{email.lower()}", settings.login_attempts_per_minute):
        raise TOO_MANY


def _fail(error: AuthError):
    raise HTTPException(error.status, str(error)) from None


@router.post("/register-company", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register_company(body: RegisterCompany, request: Request):
    _limit(request, body.email, "register")
    try:
        return auth_service.register_company(body.company_name, body.owner_name, body.email, body.password)
    except AuthError as error:
        _fail(error)


@router.post("/login", response_model=TokenPair)
def login(body: Login, request: Request):
    _limit(request, body.email, "login")
    try:
        return auth_service.login(body.email, body.password)
    except AuthError as error:
        _fail(error)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest):
    try:
        return auth_service.refresh(body.refresh_token)
    except AuthError as error:
        _fail(error)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest):
    auth_service.logout(body.refresh_token)


@router.post("/join", response_model=JoinResult, status_code=status.HTTP_201_CREATED)
def join(body: Join, request: Request):
    _limit(request, body.email, "join")
    try:
        auth_service.join(body.full_name, body.email, body.password, body.invite_token, body.company_code)
    except AuthError as error:
        _fail(error)
    return JoinResult()


@router.get("/me", response_model=MeOut)
def me(principal: CurrentUser):
    company = CompanyRepository(principal.session, principal.company_id).get()
    company_out = CompanyOut.model_validate(company)
    if not principal.is_manager:
        company_out.join_code = None          # only managers hand out the join code
    return MeOut(user=UserOut.model_validate(principal.user), company=company_out)


FORGOT_ANSWER = {"detail": "If an account uses this address, we have sent it a link to choose a new password."}


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(body: PasswordForgot, request: Request) -> dict:
    """Always the same answer, so the endpoint cannot be used to find out who has an account."""
    _limit(request, body.email, "reset")
    auth_service.request_password_reset(body.email)
    return FORGOT_ANSWER


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(body: PasswordReset, request: Request):
    _limit(request, "reset-token", "reset-use")
    try:
        auth_service.reset_password(body.token, body.new_password)
    except AuthError as error:
        _fail(error)


@router.post("/change-password", response_model=TokenPair)
def change_password(body: PasswordChange, principal: CurrentUser, request: Request):
    _limit(request, principal.user.email, "password")
    try:
        return auth_service.change_password(principal.session, principal.user, body.current_password,
                                            body.new_password)
    except AuthError as error:
        _fail(error)
