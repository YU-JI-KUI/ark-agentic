"""Studio user-grants ORM table — own DeclarativeBase.

The feature owns its own ``DeclarativeBase`` so ``init_schema()`` here
creates only the ``studio_users`` table — no cross-domain coupling.

``StudioUserRow`` is the ORM row class; ``StudioUser`` (a frozen dataclass
returned by ``AuthProvider.authenticate()``) lives in
``studio.services.auth.provider`` — different concern, different name.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AuthBase(DeclarativeBase):
    """Declarative base for studio auth tables."""


class StudioUserRow(AuthBase):
    """Studio user role grants."""

    __tablename__ = "studio_users"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
