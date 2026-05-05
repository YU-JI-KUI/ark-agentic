"""initial studio auth schema (studio_users)

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
        "studio_users",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("studio_users")
