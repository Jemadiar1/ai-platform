"""
Plantilla para archivos de migración de Alembic.

Genera migraciones con formato: YYYYMMDD_XXXX_short_description.py
"""

from alembic import op
import sqlalchemy as sa
% if message:%
import logging

logger = logging.getLogger(__name__)
% endif
# revision identifiers, used by Alembic.
revision = <%=(short_revisions[0] if short_revisions else 'None')%>
down_revision = <%=(parent_revisions[0] if parent_revisions else 'None')%>
branch_labels = <%# = branch_labels if branch_labels else None %>
depends_on = <%# = depends_on if depends_on else None %>


def upgrade() -> None:
    """
    Ejecutar la migración hacia adelante.
    """
    % if message:%
    if logger.isEnabledFor(logging.INFO):
        logger.info("%s" % message)
    % endif
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """
    Revertir la migración.
    """
    % if message:%
    if logger.isEnabledFor(logging.INFO):
        logger.info("Revertiendo migración: %s" % message)
    % endif
    ${downgrades if downgrades else "pass"}
