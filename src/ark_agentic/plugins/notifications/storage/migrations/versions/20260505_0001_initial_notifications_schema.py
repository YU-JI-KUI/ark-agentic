"""initial notifications schema

Revision ID: 0001
Revises:
Create Date: 2026-05-05 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.String(64), primary_key=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_notif_agent_user_read",
        "notifications",
        ["agent_id", "user_id", "read"],
    )


def downgrade() -> None:
    op.drop_index("ix_notif_agent_user_read", table_name="notifications")
    op.drop_table("notifications")
