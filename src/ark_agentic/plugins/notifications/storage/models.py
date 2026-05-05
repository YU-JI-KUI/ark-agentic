"""Notifications ORM tables — own DeclarativeBase.

The feature owns its own ``DeclarativeBase`` so ``init_schema()`` here
creates only this feature's tables. No cross-domain ``Base.metadata``
coupling.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class NotificationsBase(DeclarativeBase):
    """Declarative base for notifications tables."""


class NotificationRow(NotificationsBase):
    __tablename__ = "notifications"

    notification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[str] = mapped_column(String(255))
    payload_json: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float]

    __table_args__ = (
        Index("ix_notif_agent_user_read", "agent_id", "user_id", "read"),
    )
