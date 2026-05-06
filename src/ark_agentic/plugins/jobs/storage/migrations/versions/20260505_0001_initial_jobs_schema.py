"""initial jobs schema (job_runs)

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
        "job_runs",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("job_id", sa.String(128), primary_key=True),
        sa.Column("last_run_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("job_runs")
