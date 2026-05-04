"""Backward-compat shim. Prefer ``studio.services.auth`` (new home).

This module forwards every symbol that used to live here. Removed in a
future release.
"""

from .auth import (  # noqa: F401
    InvalidStudioRoleError,
    LastAdminError,
    StudioAuthzError,
    StudioPrincipal,
    StudioRole,
    StudioUserNotFoundError,
    StudioUserPage,
    StudioUserRecord,
    StudioUserRepository,
    VALID_STUDIO_ROLES,
    build_studio_user_repository,
    ensure_studio_schema,
    get_studio_user_repo,
    issue_studio_token,
    issue_studio_token_id,
    require_studio_roles,
    require_studio_user,
    reset_studio_user_repo_cache,
    set_studio_user_repo_for_testing,
)

__all__ = [
    "StudioRole",
    "VALID_STUDIO_ROLES",
    "StudioUserRecord",
    "StudioUserPage",
    "StudioPrincipal",
    "StudioUserRepository",
    "StudioAuthzError",
    "InvalidStudioRoleError",
    "LastAdminError",
    "StudioUserNotFoundError",
    "build_studio_user_repository",
    "issue_studio_token",
    "issue_studio_token_id",
    "require_studio_user",
    "require_studio_roles",
    "get_studio_user_repo",
    "ensure_studio_schema",
    "reset_studio_user_repo_cache",
    "set_studio_user_repo_for_testing",
]
