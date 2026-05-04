"""Notifications feature wiring.

Two seams between core and the notifications feature:
- ``setup_notifications(app)`` — module-load time: mount HTTP routes.
- ``build_notifications_context()`` — lifespan: build runtime state.

The split mirrors FastAPI's lifecycle: routes register before lifespan
startup; the context (a ``NotificationsService`` that wraps delivery +
per-agent repos) is built inside lifespan so it can use freshly-bootstrapped
storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .delivery import NotificationDelivery
from .paths import get_notifications_base_dir
from .service import NotificationsService

if TYPE_CHECKING:
    from fastapi import FastAPI


@dataclass
class NotificationsContext:
    """Runtime state for the notifications feature.

    Single field — ``service`` — exposes the entire feature to the rest
    of the application. Storage repositories and the SSE delivery channel
    live behind it.
    """

    service: NotificationsService

    @property
    def delivery(self) -> NotificationDelivery:
        """Convenience accessor for legacy callers (jobs scanner, tests).
        Production handlers should call typed methods on ``service`` instead."""
        return self.service.delivery


def setup_notifications(app: "FastAPI") -> None:
    """Mount the notifications + jobs HTTP routes on ``app``."""
    from . import api as notifications_api

    app.include_router(notifications_api.router)


def build_notifications_context() -> NotificationsContext:
    """Build the runtime context. Called once per lifespan startup."""
    return NotificationsContext(
        service=NotificationsService(
            base_dir=get_notifications_base_dir(),
        ),
    )
