"""Make channel_mappings.tenant_id nullable for first-time channel users.

El primer mensaje de un usuario de canal externo (Telegram, Discord, WhatsApp)
llega sin tenant_id asociado. El mapeo se enriquece después con el tenant_id
real cuando se procesa el mensaje y se resuelve la identidad del usuario.

Esta migración hace tenant_id nullable.

Revisión: 2026-05-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_make_channel_mappings_tenant_nullable"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Hacer tenant_id nullable en channel_mappings."""
    op.execute("ALTER TABLE channel_mappings ALTER COLUMN tenant_id DROP NOT NULL")


def downgrade() -> None:
    """Restaurar NOT NULL en tenant_id.

    Nota: esto fallará si existen rows con tenant_id NULL.
    """
    op.execute("ALTER TABLE channel_mappings ALTER COLUMN tenant_id SET NOT NULL")
