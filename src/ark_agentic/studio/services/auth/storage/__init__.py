"""Studio user-repository storage adapters (sqlite-only).

Imported as a side-effect of ``studio/services/auth/factory.py`` so
``StudioUserRow`` registers on ``core.db.base.Base.metadata`` before
``init_schema()`` runs.
"""

from .sqlite import SqliteStudioUserRepository

__all__ = ["SqliteStudioUserRepository"]
