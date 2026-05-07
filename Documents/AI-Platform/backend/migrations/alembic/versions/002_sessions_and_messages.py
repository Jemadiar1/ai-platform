"""
Migración: agregar tablas de sesiones y mensajes para Ragnar.

Esta migración añade:
- sessions: sesiones de conversación (lifecycle, lineage, tracking)
- messages: historial de mensajes por sesión

Inspirado en el sistema de sesiones de Hermes Agent.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crear tablas sessions y messages."""
    
    # Tabla: sessions
    op.create_table(
        'sessions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.String(255), nullable=True),
        sa.Column('title', sa.String(255), nullable=False, server_default='Nueva sesión'),
        sa.Column('parent_session_id', sa.Uuid(), nullable=True),
        sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('token_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_sessions_tenant_id', 'tenant_id'),
        sa.Index('ix_sessions_parent', 'parent_session_id')
    )
    
    # Tabla: messages
    op.create_table(
        'messages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('session_id', sa.Uuid(), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('tool_calls', sa.JSON(), nullable=True),
        sa.Column('tool_name', sa.String(100), nullable=True),
        sa.Column('token_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('finish_reason', sa.String(50), nullable=True),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_messages_session_id', 'session_id')
    )
    
    # Tabla: tenant_skills (para el SkillManager de Ragnar)
    op.create_table(
        'tenant_skills',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('version', sa.String(20), nullable=True, server_default='1.0.0'),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_tenant_skill'),
        sa.Index('ix_tenant_skills_tenant_id', 'tenant_id')
    )


def downgrade() -> None:
    """Eliminar tablas."""
    op.drop_table('tenant_skills')
    op.drop_table('messages')
    op.drop_table('sessions')
