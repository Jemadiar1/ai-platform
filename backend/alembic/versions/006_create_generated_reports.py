"""Create generated_reports table.

Tabla para reportes generados con múltiples formatos:
- HTML, PDF, DOCX, XLSX, CSV
- ReportSpec serializado como JSON
- Blobs binarios para PDF/DOCX/XLSX

Revisión: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("audience", sa.String(255), nullable=False),
        sa.Column("generated_formats", sa.JSON(), nullable=False),
        sa.Column("report_spec", sa.JSON(), nullable=False),
        sa.Column("html_content", sa.Text()),
        sa.Column("pdf_blob", sa.LargeBinary()),
        sa.Column("docx_blob", sa.LargeBinary()),
        sa.Column("xlsx_blob", sa.LargeBinary()),
        sa.Column("csv_content", sa.Text()),
        sa.Column("file_size_bytes", sa.Integer(), server_default="0"),
        sa.Column("rendering_time_ms", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_generated_reports_tenant_id", "generated_reports", ["tenant_id"])
    op.create_index("ix_generated_reports_created_at", "generated_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("generated_reports")
