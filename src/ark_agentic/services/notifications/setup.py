"""Notifications feature wiring.

Two seams between core and the notifications feature:
- ``setup_notifications(app)`` — module-load time: mount HTTP routes.
- ``build_notifications_context()`` — lifespan: build runtime state.

This split mirrors FastAPI's lifecycle: routes register before lifespan
startup; the context (delivery + per-agent repo cache) is built inside
lifespan so it can use freshly-bootstrapped storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .delivery import NotificationDelivery
from .factory import build_notification_repository
from .paths import get_notifications_base_dir
from .protocol import NotificationRepository

if TYPE_CHECKING:
    from fastapi import FastAPI


@dataclass
class NotificationsContext:
    """Runtime state for the notifications feature.

    ``per_agent_repos`` is a typed cache of per-agent repositories,
    populated lazily by route handlers via ``get_or_build_repo``.
    """

    delivery: NotificationDelivery
    base_dir: Path
    per_agent_repos: dict[str, NotificationRepository] = field(default_factory=dict)

    def get_or_build_repo(self, agent_id: str) -> NotificationRepository:
        """Fetch the agent's repository, building (and caching) on miss."""
        repo = self.per_agent_repos.get(agent_id)
        if repo is None:
            repo = build_notification_repository(
                base_dir=self.base_dir / agent_id,
                agent_id=agent_id,
            )
            self.per_agent_repos[agent_id] = repo
        return repo


def setup_notifications(app: "FastAPI") -> None:
    """Mount the notifications + jobs HTTP routes on ``app``."""
    from ...api import notifications as notifications_api

    app.include_router(notifications_api.router)


def build_notifications_context() -> NotificationsContext:
    """Build the runtime context. Called once per lifespan startup."""
    return NotificationsContext(
        delivery=NotificationDelivery(),
        base_dir=get_notifications_base_dir(),
    )
