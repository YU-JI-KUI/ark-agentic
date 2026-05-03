"""Single declarative Base shared by all ORM models.

Every ORM table — both core business tables (PR2) and ``studio_users``
(migrated in Task 11) — must register against this Base so that a single
``Base.metadata.create_all(engine)`` call in lifespan creates everything.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide declarative base."""
