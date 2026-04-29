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

from ark_agentic.studio.services.auth import AuthCredentials
from ark_agentic.studio.services.auth_service import authenticate_studio_user
from ark_agentic.studio.services.authz_service import StudioRole, get_studio_user_store, issue_studio_token

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


def _auth_credentials_from_request(req: LoginRequest, request: Request) -> AuthCredentials:
    return AuthCredentials(
        username=req.username,
        password=req.password,
        client_ip=request.client.host if request.client else None,
        headers={key.lower(): value for key, value in request.headers.items()},
    )


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request):
    studio_user = await authenticate_studio_user(_auth_credentials_from_request(req, request))
    if studio_user is None:
        raise HTTPException(status_code=401, detail=INVALID_LOGIN_DETAIL)

    record = get_studio_user_store().ensure_user(
        studio_user.user_id,
        default_role=studio_user.default_role,
    )

    return LoginResponse(
        user_id=studio_user.user_id,
        role=record.role,
        display_name=studio_user.display_name,
        token=issue_studio_token(studio_user.user_id),
    )
