"""Studio Auth API.

No cookie sessions. Frontend stores the validated user object in localStorage.

``STUDIO_AUTH_PROVIDERS`` is a comma-separated provider list, defaulting to
``internal``. Internal user entries use ``password_hash`` (bcrypt) only.
Optional env ``STUDIO_USERS`` is JSON mapping username -> record.

Generate ``password_hash`` without putting secrets in shell history::

    uv run --extra server python -c "import bcrypt,getpass;print(bcrypt.hashpw(getpass.getpass().encode(),bcrypt.gensalt(12)).decode())"
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ark_agentic.plugins.studio.services.auth import (
    AuthCredentials,
    StudioRole,
    get_studio_user_repo,
    issue_studio_token,
    issue_studio_token_id,
)
from ark_agentic.plugins.studio.services.auth_service import authenticate_studio_user, logout_studio_user

router = APIRouter()
INVALID_LOGIN_DETAIL = "Invalid username or password"


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user_id: str
    role: StudioRole
    display_name: str
    token: str
    token_id: str


class LogoutResponse(BaseModel):
    status: str = "ok"
    result: bool | None = None


def _client_ip_from_request(request: Request) -> str:
    return request.client.host if request.client else "127.0.0.1"


def _headers_from_request(request: Request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.headers.items()}


def _auth_credentials_from_request(req: LoginRequest, request: Request) -> AuthCredentials:
    return AuthCredentials(
        username=req.username,
        password=req.password,
        client_ip=_client_ip_from_request(request),
        headers=_headers_from_request(request),
    )


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request):
    studio_user = await authenticate_studio_user(_auth_credentials_from_request(req, request))
    if studio_user is None:
        raise HTTPException(status_code=401, detail=INVALID_LOGIN_DETAIL)

    record = await get_studio_user_repo().ensure_user(
        studio_user.user_id,
        default_role=studio_user.default_role,
    )

    return LoginResponse(
        user_id=studio_user.user_id,
        role=record.role,
        display_name=studio_user.display_name,
        token=issue_studio_token(studio_user.user_id),
        token_id=issue_studio_token_id(studio_user.user_id),
    )


@router.post("/auth/logout", response_model=LogoutResponse)
async def logout(request: Request):
    headers = _headers_from_request(request)
    logout_result = await logout_studio_user(
        client_ip=_client_ip_from_request(request),
        headers=headers,
        # Surface the token id (set by the frontend on logout) as a
        # first-class kwarg so providers can invalidate it without
        # having to grep the headers dict.
        token_id=headers.get("x-token-id"),
    )
    return LogoutResponse(result=logout_result)
