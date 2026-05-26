"""create kb_documents table

Revision ID: 009
Revises: 008
Create Date: 2026-05-26

Creates kb_documents table for persistent knowledge base storage.
Replaces the in-memory dict-based KnowledgeBase with DB-backed storage.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kb_documents",
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
            index=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("metadata", postgresql.JSON, nullable=False, server_default="{}"),
        sa.Column(
            "embedding",
            postgresql.JSON,
            nullable=True,
            doc="Embedding vector (placeholder for pgvector)",
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
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_kb_documents_tenant_id"),
        "kb_documents",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_kb_documents_tenant_id"), table_name="kb_documents")
    op.drop_table("kb_documents")
