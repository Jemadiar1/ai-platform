"""Migration: add extracted_text column to DocumentArtifact."""

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        "document_artifacts",
        sa.Column(
            "extracted_text",
            sa.Text(),
            nullable=True,
            server_default=sa.text("'undefined'"),
        ),
    )


def downgrade():
    op.drop_column("document_artifacts", "extracted_text")