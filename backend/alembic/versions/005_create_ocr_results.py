"""Create ocr_results table.

Tabla para resultados de análisis OCR con trazabilidad:
- Imagen fuente, formato, tamaño
- Texto extraído, confianza general
- Motor usado (tesseract, paddle)
- Datos de gráficos detectados
- Advertencias generadas

Revisión: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_filename", sa.String(500)),
        sa.Column("source_format", sa.String(20), nullable=False),
        sa.Column("source_size_bytes", sa.Integer(), nullable=False),
        sa.Column("full_text", sa.Text()),
        sa.Column("overall_confidence", sa.Float(), nullable=False),
        sa.Column("engine_used", sa.String(20), nullable=False),
        sa.Column("charts_data", sa.JSON(), server_default="{}"),
        sa.Column("warnings", sa.JSON(), server_default="[]"),
        sa.Column("page_count", sa.Integer(), server_default="1"),
        sa.Column("processing_time_ms", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # Índices
    op.create_index("ix_ocr_results_tenant_id", "ocr_results", ["tenant_id"])
    op.create_index("ix_ocr_results_created_at", "ocr_results", ["created_at"])


def downgrade() -> None:
    op.drop_table("ocr_results")
