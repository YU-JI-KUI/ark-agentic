"""Core declarative Base — registers core ORM tables only.

Each independent feature owns its own ``DeclarativeBase`` (and its own
``metadata``) so ``init_schema()`` in that feature creates only that
feature's tables. The previously-shared ``Base.metadata`` was a hidden
coupling: deleting a feature would have left orphan tables behind.

- Core tables (this Base): SessionMeta, SessionMessage, UserMemory.
- Jobs: ``plugins.jobs.storage.models.JobsBase``.
- Notifications: ``plugins.notifications.storage.models.NotificationsBase``.
- Studio user grants: ``plugins.studio.services.auth.storage.models.AuthBase``.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Core domain declarative base (sessions + user memory)."""
