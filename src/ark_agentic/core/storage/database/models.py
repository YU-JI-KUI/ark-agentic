"""Core ORM models — sessions, user memory.

Each feature owns its own ``DeclarativeBase``; this Base is core-only.
Every table here inherits :class:`AgentScoped`, so ``agent_id`` is
auto-injected by the event listener in ``scoping.py``.
"""

from __future__ import annotations

from sqlalchemy import (
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .scoping import AgentScoped


class SessionMeta(AgentScoped, Base):
    __tablename__ = "session_meta"

    session_id: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    compaction_count: Mapped[int] = mapped_column(Integer, default=0)
    active_skill_ids_json: Mapped[str] = mapped_column(Text, default="[]")

    # Composite PK closes the cross-agent ON CONFLICT DO UPDATE leak —
    # session_ids are only unique within an agent.
    __table_args__ = (
        PrimaryKeyConstraint("agent_id", "session_id"),
        Index(
            "ix_session_meta_agent_user_updated_at",
            "agent_id",
            "user_id",
            text("updated_at DESC"),
        ),
    )


class SessionMessage(AgentScoped, Base):
    __tablename__ = "session_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Composite FK + ON DELETE CASCADE (PRAGMA foreign_keys=ON in engine.py)
    # keep messages from outliving their parent session.
    session_id: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[str] = mapped_column(String(255))
    seq: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_id", "session_id"],
            ["session_meta.agent_id", "session_meta.session_id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_session_messages_agent_session_seq",
            "agent_id",
            "session_id",
            "seq",
            unique=True,
        ),
        Index(
            "ix_session_messages_agent_user",
            "agent_id",
            "user_id",
        ),
    )


class UserMemory(AgentScoped, Base):
    __tablename__ = "user_memory"

    user_id: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, default="")
    # NULL until the dreamer first consolidates this user's memory.
    last_dream_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[int] = mapped_column(Integer, default=0)

    # Same user_id lives independently under each agent.
    __table_args__ = (
        PrimaryKeyConstraint("agent_id", "user_id"),
        Index(
            "ix_user_memory_agent_updated_at",
            "agent_id",
            text("updated_at DESC"),
        ),
    )
