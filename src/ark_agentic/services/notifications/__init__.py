"""Notifications: domain models + delivery dispatcher.

Persistence is owned by ``core.storage`` repositories (file or SQLite).
This package no longer exports a standalone ``NotificationStore`` class —
build a backend via ``core.storage.factory.build_notification_repository``.
"""

from .delivery import NotificationDelivery
from .models import Notification, NotificationList
from .paths import get_notifications_base_dir

__all__ = [
    "Notification",
    "NotificationList",
    "NotificationDelivery",
    "get_notifications_base_dir",
]
