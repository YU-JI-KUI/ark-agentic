"""Storage protocols - typing.Protocol definitions.

业务代码只依赖此包；任何后端实现都必须满足这些 Protocol。
"""

from .agent_state import AgentStateRepository
from .cache import Cache
from .memory import MemoryRepository
from .session import SessionRepository
from .studio_user import (
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

__all__ = [
    "AgentStateRepository",
    "Cache",
    "MemoryRepository",
    "SessionRepository",
    "StudioUserRepository",
    "StudioUserRecord",
    "StudioUserPage",
    "StudioRole",
    "VALID_STUDIO_ROLES",
    "StudioAuthzError",
    "InvalidStudioRoleError",
    "LastAdminError",
    "StudioUserNotFoundError",
]
