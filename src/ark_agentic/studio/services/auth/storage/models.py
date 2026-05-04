"""Studio user-grants ORM table.

Lives in the studio auth feature package — core no longer knows about
this table. The class still extends ``core.db.base.Base`` so one shared
``Base.metadata`` covers all features served by the same engine.

Renamed from ``StudioUser`` to ``StudioUserRow`` to avoid clashing with
the ``StudioUser`` dataclass that ``AuthProvider.authenticate()`` returns
(``studio.services.auth.provider``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .....core.db.base import Base


class StudioUserRow(Base):
    """Studio user role grants."""

    __tablename__ = "studio_users"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
