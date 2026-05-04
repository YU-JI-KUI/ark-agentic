"""Notification storage adapters (file / sqlite).

Imported as a side-effect of ``services/notifications/factory.py`` so the
``NotificationRow`` ORM model registers on ``core.db.base.Base.metadata``
before ``init_schema()`` runs.
"""

from .file import FileNotificationRepository
from .sqlite import SqliteNotificationRepository

__all__ = [
    "FileNotificationRepository",
    "SqliteNotificationRepository",
]
