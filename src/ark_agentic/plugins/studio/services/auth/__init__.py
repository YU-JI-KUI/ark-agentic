"""Studio authentication & authorization feature.

Self-contained: tokens, principal/dependencies, user repository (Protocol +
adapters + factory), and the singleton accessor all live here. ``app.py``
bootstraps the schema via ``ensure_studio_schema()``.
"""

from .factory import build_studio_user_repository
from .internal_provider import InternalAuthProvider
from .principal import StudioPrincipal, require_studio_roles, require_studio_user
from .protocol import (
    InvalidStudioRoleError,
    LastAdminError,
    StudioAuthzError,
    StudioRole,
    StudioUserNotFoundError,
    StudioUserPage,
    StudioUserRecord,
    StudioUserRepository,
    VALID_STUDIO_ROLES,
)
from .provider import AuthCredentials, AuthProvider, StudioUser
from .repo_singleton import (
    ensure_studio_schema,
    get_studio_user_repo,
    reset_studio_user_repo_cache,
    set_studio_user_repo_for_testing,
)
from .tokens import issue_studio_token, issue_studio_token_id

__all__ = [
    # Provider layer
    "AuthCredentials",
    "AuthProvider",
    "InternalAuthProvider",
    "StudioUser",
    # Authorization (roles, principal, deps)
    "StudioPrincipal",
    "StudioRole",
    "VALID_STUDIO_ROLES",
    "StudioUserRecord",
    "StudioUserPage",
    "StudioUserRepository",
    "StudioAuthzError",
    "InvalidStudioRoleError",
    "LastAdminError",
    "StudioUserNotFoundError",
    "require_studio_user",
    "require_studio_roles",
    # Tokens
    "issue_studio_token",
    "issue_studio_token_id",
    # Repo singleton
    "build_studio_user_repository",
    "get_studio_user_repo",
    "ensure_studio_schema",
    "reset_studio_user_repo_cache",
    "set_studio_user_repo_for_testing",
]
