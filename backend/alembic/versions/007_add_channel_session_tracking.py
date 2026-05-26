"""add channel session tracking

Revision ID: 007
Revises: 006
Create Date: 2026-05-26

Adds last_session_id and channel_type to channel_mappings to enable
session continuity for Telegram users.
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_mappings", sa.Column("last_session_id", sa.UUID(), nullable=True))
    op.add_column("channel_mappings", sa.Column("channel_type", sa.String(50), nullable=True))
    op.create_index(
        op.f("ix_channel_mappings_last_session_id"),
        "channel_mappings",
        ["last_session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_channel_mappings_last_session_id"), table_name="channel_mappings")
    op.drop_column("channel_mappings", "channel_type")
    op.drop_column("channel_mappings", "last_session_id")
