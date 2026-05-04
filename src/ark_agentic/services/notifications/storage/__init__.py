"""Notification storage adapters (file / sqlite).

``NotificationRow`` registers on the feature-local ``NotificationsBase``
metadata, created by ``services.notifications.engine.init_schema()``.
"""

from .file import FileNotificationRepository
from .sqlite import SqliteNotificationRepository

__all__ = [
    "FileNotificationRepository",
    "SqliteNotificationRepository",
]
