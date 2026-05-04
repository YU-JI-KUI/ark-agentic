"""Notifications feature — domain models + repositories + delivery.

Self-contained: this package owns its Protocol, file/sqlite adapters, ORM
table, and factory. ``app.py`` is the only place that wires it into the
larger application via ``setup_notifications(app)``.
"""

from .delivery import NotificationDelivery
from .factory import build_notification_repository
from .models import Notification, NotificationList
from .paths import get_notifications_base_dir
from .protocol import NotificationRepository
from .setup import setup_notifications

__all__ = [
    "Notification",
    "NotificationList",
    "NotificationDelivery",
    "NotificationRepository",
    "build_notification_repository",
    "get_notifications_base_dir",
    "setup_notifications",
]
