"""add tenant_agents table

Revision ID: 012
Revises: 011
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_agents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=sa.func.uuid_generate_v4(),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "agent_name",
            sa.String(50),
            nullable=False,
            doc="Module name: ai-connect, ai-analytics, etc.",
        ),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            default=True,
            doc="Whether the agent is currently enabled for this tenant",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            doc="When the agent access expires (None = permanent)",
        ),
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_tenant_agents_tenant_id"), "tenant_agents", ["tenant_id"], unique=False)
    op.create_unique_constraint(
        "uq_tenant_agents_tenant_agent",
        "tenant_agents",
        ["tenant_id", "agent_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_tenant_agents_tenant_agent", "tenant_agents", type_="unique")
    op.drop_index(op.f("ix_tenant_agents_tenant_id"), table_name="tenant_agents")
    op.drop_table("tenant_agents")