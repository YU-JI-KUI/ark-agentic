"""ORM models — single source of truth for the SQLite (and future PG) schema.

Note: ``studio_users`` is moved into this module by Task 11 so all tables share
``Base.metadata`` and a single ``init_schema`` call creates everything.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SessionMeta(Base):
    __tablename__ = "session_meta"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    updated_at: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    session_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    compaction_count: Mapped[int] = mapped_column(Integer, default=0)
    active_skill_ids_json: Mapped[str] = mapped_column(Text, default="[]")


class SessionMessage(Base):
    __tablename__ = "session_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ON DELETE CASCADE pairs with PRAGMA foreign_keys=ON in core.db.engine
    # so that direct DELETEs of session_meta rows (migrations, admin tools)
    # do not leave orphaned message rows behind.
    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("session_meta.session_id", ondelete="CASCADE"),
    )
    user_id: Mapped[str] = mapped_column(String(255))
    seq: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index(
            "ix_session_messages_session_seq",
            "session_id",
            "seq",
            unique=True,
        ),
        Index("ix_session_messages_user", "user_id"),
    )


class UserMemory(Base):
    __tablename__ = "user_memory"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[int] = mapped_column(Integer, default=0)


class AgentState(Base):
    __tablename__ = "agent_state"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[int] = mapped_column(Integer, default=0)


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


class StudioUser(Base):
    """Studio user role grants.

    Migrated here from ``studio.services.authz_service`` (Task 11) so the
    table joins the global metadata and gets created by the unified
    ``init_schema(engine)`` call. The Table object surfaces for legacy
    SQLAlchemy Core queries via ``StudioUser.__table__``.
    """

    __tablename__ = "studio_users"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
