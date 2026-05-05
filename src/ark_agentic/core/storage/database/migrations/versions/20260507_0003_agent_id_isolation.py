"""agent isolation: add agent_id to session_meta / session_messages / user_memory

Adds a NOT NULL ``agent_id`` column to every agent-partitioned table and
recreates indexes with ``agent_id`` as the leading key. ``user_memory``
gains a composite ``(agent_id, user_id)`` primary key.

Dev data is discarded — the upgrade drops and recreates every affected
table. Running this on a populated DB will lose data; this is acceptable
for the single pre-launch deployment.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-07 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the agent-partitioned tables. ``session_messages`` first because
    # of its FK into ``session_meta``.
    op.drop_index(
        "ix_session_messages_session_seq", table_name="session_messages",
    )
    op.drop_index(
        "ix_session_messages_user", table_name="session_messages",
    )
    op.drop_table("session_messages")

    op.drop_index(
        "ix_session_meta_user_updated_at", table_name="session_meta",
    )
    op.drop_table("session_meta")

    op.drop_table("user_memory")

    # Recreate with agent_id as part of the schema. The PK on session_meta
    # is composite so per-agent session_ids cannot collide via ON CONFLICT.
    op.create_table(
        "session_meta",
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
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
        sa.PrimaryKeyConstraint("agent_id", "session_id"),
    )
    op.create_index(
        "ix_session_meta_agent_user_updated_at",
        "session_meta",
        ["agent_id", "user_id", sa.text("updated_at DESC")],
    )

    op.create_table(
        "session_messages",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True,
        ),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id", "session_id"],
            ["session_meta.agent_id", "session_meta.session_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_session_messages_agent_session_seq",
        "session_messages",
        ["agent_id", "session_id", "seq"],
        unique=True,
    )
    op.create_index(
        "ix_session_messages_agent_user",
        "session_messages",
        ["agent_id", "user_id"],
    )

    op.create_table(
        "user_memory",
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("last_dream_at", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("agent_id", "user_id"),
    )
    op.create_index(
        "ix_user_memory_agent_updated_at",
        "user_memory",
        ["agent_id", sa.text("updated_at DESC")],
    )


def downgrade() -> None:
    # Recreating the previous schema also discards data — symmetric with
    # the upgrade for a pre-launch dev DB.
    op.drop_index(
        "ix_user_memory_agent_updated_at", table_name="user_memory",
    )
    op.drop_table("user_memory")

    op.drop_index(
        "ix_session_messages_agent_user", table_name="session_messages",
    )
    op.drop_index(
        "ix_session_messages_session_seq", table_name="session_messages",
    )
    op.drop_table("session_messages")

    op.drop_index(
        "ix_session_meta_agent_user_updated_at", table_name="session_meta",
    )
    op.drop_table("session_meta")

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
        "ix_session_meta_user_updated_at",
        "session_meta",
        ["user_id", sa.text("updated_at DESC")],
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
