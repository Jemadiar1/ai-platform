"""create user_profiles table

Revision ID: 008
Revises: 007
Create Date: 2026-05-26

Creates user_profiles table for cross-session user memory.
Stores user preferences, personal data, and behavioral patterns
that persist across all sessions for a given user.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=sa.func.uuid_generate_v4(),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "user_id",
            sa.String(255),
            nullable=False,
            doc="Telegram user_id, Clerk user_id, etc.",
        ),
        sa.Column(
            "content",
            sa.Text,
            nullable=False,
            doc="Perfil estructurado del usuario (§-delimited)",
        ),
        sa.Column("char_count", sa.Integer, nullable=False, default=0),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_user_profiles_tenant_user"),
    )
    op.create_index(
        op.f("ix_user_profiles_user_id"),
        "user_profiles",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_profiles_user_id"), table_name="user_profiles")
    op.drop_table("user_profiles")
