"""Studio user-repository storage adapters (sqlite-only).

``StudioUserRow`` registers on the feature-local ``AuthBase`` metadata,
created by ``studio.services.auth.engine.init_schema()``.
"""

from .sqlite import SqliteStudioUserRepository

__all__ = ["SqliteStudioUserRepository"]
