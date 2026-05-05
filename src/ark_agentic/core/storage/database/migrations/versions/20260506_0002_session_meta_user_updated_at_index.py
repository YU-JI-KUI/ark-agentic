"""composite index on session_meta(user_id, updated_at DESC)

Drops ``ix_session_meta_user_id`` (user_id only) and adds
``ix_session_meta_user_updated_at`` so the Studio listing query
(``WHERE user_id=? ORDER BY updated_at DESC``) and the dashboard admin
scan (``ORDER BY updated_at DESC``) both walk an index without a temp
B-tree sort.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-06 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_session_meta_user_id", table_name="session_meta")
    op.create_index(
        "ix_session_meta_user_updated_at",
        "session_meta",
        ["user_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_meta_user_updated_at", table_name="session_meta",
    )
    op.create_index(
        "ix_session_meta_user_id", "session_meta", ["user_id"],
    )
