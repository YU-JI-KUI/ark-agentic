"""initial core schema (sessions + user memory)

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
        "session_meta",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("compaction_count", sa.Integer(), nullable=False),
        sa.Column("active_skill_ids_json", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_session_meta_user_id", "session_meta", ["user_id"],
    )

    op.create_table(
        "session_messages",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True,
        ),
        sa.Column(
            "session_id",
            sa.String(128),
            sa.ForeignKey(
                "session_meta.session_id", ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_session_messages_session_seq",
        "session_messages",
        ["session_id", "seq"],
        unique=True,
    )
    op.create_index(
        "ix_session_messages_user", "session_messages", ["user_id"],
    )

    op.create_table(
        "user_memory",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("last_dream_at", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_memory")
    op.drop_index(
        "ix_session_messages_user", table_name="session_messages",
    )
    op.drop_index(
        "ix_session_messages_session_seq", table_name="session_messages",
    )
    op.drop_table("session_messages")
    op.drop_index("ix_session_meta_user_id", table_name="session_meta")
    op.drop_table("session_meta")
