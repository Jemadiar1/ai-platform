"""create decision_feedback table

Revision ID: 011
Revises: 010
Create Date: 2026-05-26

Creates decision_feedback table for collecting user ratings
on Odin's routing and module execution decisions.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "011"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=sa.func.uuid_generate_v4(),
        ),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.String(255),
            nullable=False,
        ),
        sa.Column(
            "rating",
            sa.Integer,
            nullable=False,
            doc="1=down, 2=neutral, 3=up",
        ),
        sa.Column(
            "comment",
            sa.Text,
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("decision_feedback")
