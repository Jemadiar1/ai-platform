"""Create document ingestion tables.

Tablas para ingestión asíncrona de documentos:
- document_artifacts: documentos subidos para procesamiento
- document_chunks: chunks de texto extraído
- document_fts_index: índice de búsqueda full-text (tsvector)

Revisión: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table: document_artifacts
    op.create_table(
        "document_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), server_default="0"),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("storage_backend", sa.String(50), server_default="local"),
        sa.Column("status", sa.String(30), server_default="pending"),
        sa.Column("error", sa.Text()),
        sa.Column("celery_task_id", sa.String(255)),
        sa.Column("page_count", sa.Integer()),
        sa.Column("language", sa.String(10), server_default="es"),
        sa.Column("checksum", sa.String(64)),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # Indexes for document_artifacts
    op.create_index("ix_document_artifacts_tenant_id", "document_artifacts", ["tenant_id"])
    op.create_index("ix_document_artifacts_status", "document_artifacts", ["status"])

    # Table: document_chunks
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("parent_chunk_id", postgresql.UUID(as_uuid=True)),
        sa.Column("level", sa.Integer(), server_default="1"),
        sa.Column("chunk_type", sa.String(30), server_default="text"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document_artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_chunk_id"], ["document_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # Indexes for document_chunks
    op.create_index("ix_document_chunks_tenant_id", "document_chunks", ["tenant_id"])
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_parent", "document_chunks", ["parent_chunk_id"])
    op.create_index("ix_document_chunks_level", "document_chunks", ["level"])
    op.create_index("ix_document_chunks_metadata", "document_chunks", ["metadata_json"], postgresql_using="gin")

    # Table: document_fts_index
    op.create_table(
        "document_fts_index",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("search_vector", sa.Text(), nullable=False),
        sa.Column("rank", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # Indexes for document_fts_index
    op.create_index("ix_document_fts_tenant_id", "document_fts_index", ["tenant_id"])
    op.create_index("ix_document_fts_document_id", "document_fts_index", ["document_id"])


def downgrade() -> None:
    op.drop_table("document_fts_index")
    op.drop_table("document_chunks")
    op.drop_table("document_artifacts")
