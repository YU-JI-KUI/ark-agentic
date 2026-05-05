"""Core ORM models — sessions, user memory.

Independent feature tables (notifications, jobs, studio_users, …) live in
their own feature packages with their own ``DeclarativeBase``; this Base
holds only the central ones.

Agent isolation: every table inherits :class:`AgentScoped` (see
``scoping.py``) which adds an ``agent_id`` column and binds row visibility
to the active agent context. Repositories never spell ``agent_id`` in
their WHERE clauses; the ORM event listener injects the predicate.
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

    # Composite PK: session_ids are minted per-agent and not necessarily
    # unique across agents. Without ``agent_id`` in the PK an upsert from
    # one agent could silently overwrite another agent's row through
    # ``ON CONFLICT DO UPDATE``. The composite makes such collisions
    # impossible at the schema level.
    #
    # The composite index ``(agent_id, user_id, updated_at DESC)`` covers
    # the Studio per-agent + per-user listing and the per-agent admin
    # scan ``WHERE agent_id=? ORDER BY updated_at DESC``.
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
    # Messages reference a session by its composite ``(agent_id,
    # session_id)`` key. ON DELETE CASCADE + PRAGMA foreign_keys=ON keep
    # message rows from outliving their parent session.
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
    # Timestamp (epoch seconds) of the user's last memory consolidation pass.
    # NULL until the dreamer first marks the user.
    last_dream_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[int] = mapped_column(Integer, default=0)

    # Composite PK: same ``user_id`` lives independently under each agent.
    __table_args__ = (
        PrimaryKeyConstraint("agent_id", "user_id"),
        Index(
            "ix_user_memory_agent_updated_at",
            "agent_id",
            text("updated_at DESC"),
        ),
    )
