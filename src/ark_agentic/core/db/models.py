"""Core ORM models — sessions, user memory.

Independent feature tables (notifications, jobs, studio_users, …) live in
their own feature packages with their own ``DeclarativeBase``; this Base
holds only the central ones.
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SessionMeta(Base):
    __tablename__ = "session_meta"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    updated_at: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
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
    # Timestamp (epoch seconds) of the user's last memory consolidation pass.
    # NULL until the dreamer first marks the user.
    last_dream_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[int] = mapped_column(Integer, default=0)


