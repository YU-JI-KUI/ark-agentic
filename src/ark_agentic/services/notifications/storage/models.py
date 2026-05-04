"""Notifications ORM table.

Lives in the notifications feature package — core no longer knows about
this table. The class still extends ``core.db.base.Base`` so that one
shared ``Base.metadata`` covers all features served by the same engine.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ....core.db.base import Base


class NotificationRow(Base):
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
