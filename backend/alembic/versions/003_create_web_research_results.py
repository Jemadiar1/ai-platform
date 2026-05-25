"""Create web_research_results table.

Tabla para resultados de investigación web con trazabilidad completa:
- URL consultada, fecha, contenido
- Tenant que lo solicitó
- Quién lo solicitó (módulo o orquestador)
- Hash del contenido para deduplicación

Revisión: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "web_research_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("content_type", sa.String(100)),
        sa.Column("size_bytes", sa.Integer(), server_default="0"),
        sa.Column("status_code", sa.Integer()),
        sa.Column(
            "fetch_date",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("source_by", sa.String(100), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            ondelete="SET NULL",
        ),
    )

    # Índices
    op.create_index("ix_web_research_tenant_id", "web_research_results", ["tenant_id"])
    op.create_index("ix_web_research_task_id", "web_research_results", ["task_id"])


def downgrade() -> None:
    op.drop_table("web_research_results")
