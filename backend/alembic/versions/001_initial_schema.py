"""
Migración inicial: crear todas las tablas de la base de datos.

Genera el esquema completo:
- tenants: clientes/multi-tenancy
- users: usuarios dentro de cada tenant
- tasks: tareas para agentes IA
- usage_events: registro de uso para billing
- agent_memory: memoria de agentes IA
- sessions: sesiones de conversación
- messages: mensajes dentro de sesiones
- tenant_skills: skills personalizados por tenant
- channel_mappings: mapeo de canales de comunicación
- contacts: contactos CRM
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crear todas las tablas del esquema inicial."""

    # --- tenants ---
    op.create_table(
        "tenants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column("billing_email", sa.String(255)),
        sa.Column("clerk_user_id", sa.String(255), unique=True),
        sa.Column("settings", sa.JSON(), server_default="{}"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("clerk_user_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("role", sa.String(50), server_default="member"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # --- tasks ---
    op.create_table(
        "tasks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column("payload", sa.JSON(), server_default="{}"),
        sa.Column("result", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("priority", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # --- usage_events ---
    op.create_table(
        "usage_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("task_id", sa.dialects.postgresql.UUID(as_uuid=True), index=True),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default="0"),
        sa.Column("cost_usd", sa.Float(), server_default="0.0"),
        sa.Column("extra_data", sa.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
    )

    # --- agent_memory ---
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON()),
        sa.Column("extra_data", sa.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # --- sessions ---
    op.create_table(
        "sessions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", sa.String(255)),
        sa.Column("title", sa.String(255), server_default="Nueva sesión"),
        sa.Column("parent_session_id", sa.dialects.postgresql.UUID(as_uuid=True), index=True),
        sa.Column("message_count", sa.Integer(), server_default="0"),
        sa.Column("token_count", sa.Integer(), server_default="0"),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_session_id"], ["sessions.id"], ondelete="SET NULL"),
    )

    # --- messages ---
    op.create_table(
        "messages",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("tool_calls", sa.JSON()),
        sa.Column("tool_name", sa.String(100)),
        sa.Column("token_count", sa.Integer(), server_default="0"),
        sa.Column("finish_reason", sa.String(50)),
        sa.Column("reasoning", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
    )

    # --- tenant_skills ---
    op.create_table(
        "tenant_skills",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category", sa.String(50), server_default="custom"),
        sa.Column("version", sa.String(20), server_default="1.0.0"),
        sa.Column("content", sa.Text()),
        sa.Column("enabled", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # --- channel_mappings ---
    op.create_table(
        "channel_mappings",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("channel_user_id", sa.String(255), nullable=False),
        sa.Column("channel_username", sa.String(255)),
        sa.Column("channel_chat_id", sa.String(255)),
        sa.Column("channel_type", sa.String(50)),
        sa.Column("config", sa.JSON(), server_default="{}"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "channel", "channel_user_id", name="uq_channel_mapping"),
    )

    # --- contacts ---
    op.create_table(
        "contacts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("name", sa.String(255)),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(50)),
        sa.Column("channel_id", sa.String(255)),
        sa.Column("channel_type", sa.String(50)),
        sa.Column("tags", sa.JSON(), server_default="[]"),
        sa.Column("notes", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )

    # --- Índices adicionales ---
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_tenant_status", "tasks", ["tenant_id", "status"])
    op.create_index("ix_users_tenant_email", "users", ["tenant_id", "email"])
    op.create_index("ix_usage_events_tenant_module", "usage_events", ["tenant_id", "module"])
    op.create_index("ix_agent_memory_tenant_agent", "agent_memory", ["tenant_id", "agent_id"])
    op.create_index("ix_messages_session", "messages", ["session_id"])
    op.create_index("ix_sessions_tenant", "sessions", ["tenant_id"])
    op.create_index("ix_tenant_skills_tenant_name", "tenant_skills", ["tenant_id", "name"])
    op.create_index("ix_channel_mappings_tenant_channel", "channel_mappings", ["tenant_id", "channel"])
    op.create_index("ix_contacts_tenant_email", "contacts", ["tenant_id", "email"])

    # --- Foreign keys adicionales que no se pueden definir inline en tablas ya creadas ---
    op.create_foreign_key(
        "fk_tasks_tenant", "tasks", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_users_tenant", "users", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_usage_events_tenant", "usage_events", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_usage_events_task", "usage_events", "tasks",
        ["task_id"], ["id"],
        ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_agent_memory_tenant", "agent_memory", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_sessions_tenant", "sessions", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_sessions_parent", "sessions", "sessions",
        ["parent_session_id"], ["id"],
        ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_messages_session", "messages", "sessions",
        ["session_id"], ["id"],
        ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_tenant_skills_tenant", "tenant_skills", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_channel_mappings_tenant", "channel_mappings", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_channel_mappings_user", "channel_mappings", "users",
        ["user_id"], ["id"],
        ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_contacts_tenant", "contacts", "tenants",
        ["tenant_id"], ["id"],
        ondelete="CASCADE"
    )


def downgrade() -> None:
    """Revertir todas las tablas."""
    op.drop_table("contacts")
    op.drop_table("channel_mappings")
    op.drop_table("tenant_skills")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("agent_memory")
    op.drop_table("usage_events")
    op.drop_table("tasks")
    op.drop_table("users")
    op.drop_table("tenants")
