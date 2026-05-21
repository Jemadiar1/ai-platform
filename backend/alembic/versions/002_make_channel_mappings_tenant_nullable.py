"""Make channel_mappings.tenant_id nullable for first-time channel users.

El primer mensaje de un usuario de canal externo (Telegram, Discord, WhatsApp)
llega sin tenant_id asociado. El mapeo se enriquece después con el tenant_id
real cuando se procesa el mensaje y se resuelve la identidad del usuario.

Esta migración hace tenant_id nullable y permite NULL en el foreign key.

Revisión: 2026-05-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_make_channel_mappings_tenant_nullable"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Hacer tenant_id y user_id nullable en channel_mappings."""
    # Permitir NULL en tenant_id
    op.alter_column(
        "channel_mappings",
        "tenant_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # user_id ya es nullable en la definición original, pero asegurar consistencia
    op.alter_column(
        "channel_mappings",
        "user_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # Eliminar el foreign key existente (no se puede modificar con nullable=True)
    op.drop_constraint(
        "fk_channel_mappings_tenant",
        "channel_mappings",
        type_="foreignkey",
    )

    # Re-crear el foreign key con ON DELETE CASCADE pero permitiendo NULL
    op.create_foreign_key(
        "fk_channel_mappings_tenant",
        "channel_mappings",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Restaurar la restricción NOT NULL.

    Nota: esto fallará si existen rows con tenant_id NULL.
    En producción, primero migrar esas rows a un tenant válido.
    """
    # Eliminar el foreign key actual
    op.drop_constraint(
        "fk_channel_mappings_tenant",
        "channel_mappings",
        type_="foreignkey",
    )

    # Re-crear con NOT NULL
    op.create_foreign_key(
        "fk_channel_mappings_tenant",
        "channel_mappings",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Restaurar NOT NULL
    op.alter_column(
        "channel_mappings",
        "tenant_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
