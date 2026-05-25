"""
Modelos de SQLAlchemy - Base de datos

Cada clase representa una tabla en PostgreSQL.
Todos los modelos incluyen tenant_id para multi-tenancy.

Estructura de tablas:
- tenants: clientes de NeuralCrew Labs
- users: usuarios dentro de cada tenant
- tasks: tareas a ejecutar por los agentes IA
- usage_events: registro de uso para billing

"""

from uuid import uuid4

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from ai_platform.database import Base


class Tenant(Base):
    """
    Tabla: tenants

    Representa un cliente de NeuralCrew Labs.
    Cada cliente contrata uno o más módulos de servicio.
    """

    __tablename__ = "tenants"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4, doc="UUID v4 único del tenant")
    name = Column(String(255), nullable=False, doc="Nombre de la empresa/cliente")
    slug = Column(
        String(100), unique=True, nullable=False, index=True, doc="Identificador URL único (ej: 'mi-empresa')"
    )
    plan = Column(String(50), nullable=False, default="free", doc="Plan actual: free, starter, pro, enterprise")
    billing_email = Column(String(255), doc="Email para facturación")
    clerk_user_id = Column(String(255), unique=True, nullable=True, doc="ID externo del usuario en Clerk (clerk.com)")
    settings = Column(JSON, default=dict, doc="Configuración personalizada: idioma, zona horaria, integraciones")
    is_active = Column(Boolean, default=True, doc="Estado del tenant (activo/inactivo)")

    # Timestamps automáticos
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Tenant(id={self.id}, name={self.name}, plan={self.plan})>"


class User(Base):
    """
    Tabla: users

    Usuarios dentro de un tenant.
    Un tenant puede tener múltiples usuarios.
    """

    __tablename__ = "users"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True, doc="Tenant al que pertenece este usuario")
    clerk_user_id = Column(String(255), nullable=False, doc="ID del usuario en Clerk")
    email = Column(String(255), nullable=False)
    name = Column(String(255))
    role = Column(String(50), default="member", doc="Rol: admin, member, viewer")
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


class Task(Base):
    """
    Tabla: tasks

    Cada tarea es una acción que un agente IA debe ejecutar.
    Ejemplo: "Generar post para Instagram", "Responder WhatsApp", etc.
    """

    __tablename__ = "tasks"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    module = Column(String(50), nullable=False, doc="Módulo: ai-connect, ai-social, ai-content, etc.")
    status = Column(
        String(20), nullable=False, default="pending", index=True, doc="pending, running, completed, failed, retrying"
    )
    payload = Column(JSON, default=dict, doc="Datos de la tarea en formato JSON")
    result = Column(JSON, nullable=True, doc="Resultado de la tarea")
    error = Column(Text, nullable=True, doc="Mensaje de error si falló")
    retry_count = Column(Integer, default=0)
    priority = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<Task(id={self.id}, module={self.module}, status={self.status})>"


class UsageEvent(Base):
    """
    Tabla: usage_events

    Registro de cada uso para billing.
    Cada vez que un módulo ejecuta algo, se registra aquí:
    cuántos tokens consumió, cuánto costó, en qué módulo, etc.
    """

    __tablename__ = "usage_events"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    task_id = Column(PG_UUID(as_uuid=True), nullable=True, index=True, doc="Tarea asociada a este evento de uso")
    module = Column(String(50), nullable=False, doc="Módulo que generó el evento")
    event_type = Column(String(100), nullable=False, doc="Tipo: task_execution, api_call, etc.")
    tokens_used = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    extra_data = Column(JSON, default=dict, doc="Metadatos adicionales")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<UsageEvent(tenant={self.tenant_id}, module={self.module}, cost=${self.cost_usd})>"


class AgentMemory(Base):
    """
    Tabla: agent_memory

    Memoria de los agentes IA.
    Cada agente tiene memoria de sesión (corto plazo) y memoria semántica (largo plazo).
    La memoria semántica usa embeddings (vectors) para búsqueda por similitud.

    pgvector se usa para embeddings dentro de PostgreSQL.
    """

    __tablename__ = "agent_memory"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    agent_id = Column(String(100), nullable=False, doc="ID del agente (ej: 'ai-connect', 'ai-social')")
    type = Column(String(20), nullable=False, doc="short_term (sesión) o long_term (semántica)")
    content = Column(Text, nullable=False, doc="Contenido de la memoria")
    embedding = Column(
        # pgvector usa el tipo VECTOR(N) donde N es la dimensión
        # Usamos JSON por ahora; migrar a pgvector cuando se instale la extensión
        JSON,
        nullable=True,
        doc="Embedding vector para búsqueda semántica",
    )
    extra_data = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<AgentMemory(agent={self.agent_id}, type={self.type})>"


class ConversationSession(Base):
    """
    Tabla: sessions

    Sesiones de conversación dentro de un tenant.
    Cada sesión tiene un historial de mensajes (messages table).

    Inspirado en el sistema de sesiones de Hermes Agent.
    """

    __tablename__ = "sessions"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(String(255), nullable=True, doc="ID del usuario en Clerk")
    title = Column(String(255), nullable=False, default="Nueva sesión")
    parent_session_id = Column(
        PG_UUID(as_uuid=True), nullable=True, index=True, doc="ID de sesión padre (para tracking de subagentes)"
    )
    message_count = Column(Integer, default=0)
    token_count = Column(Integer, default=0)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<ConversationSession(id={self.id}, title={self.title}, msgs={self.message_count})>"


class ChannelMapping(Base):
    """
    Tabla: channel_mappings

    Mapeo entre canales externos (Telegram, Discord, WhatsApp) y usuarios de la plataforma.
    Permite vincular un usuario de canal externo con un tenant y usuario de la plataforma.
    """

    __tablename__ = "channel_mappings"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=True, index=True)
    user_id = Column(PG_UUID(as_uuid=True), nullable=True)
    channel = Column(String(50), nullable=False)
    channel_user_id = Column(String(255), nullable=False)
    channel_username = Column(String(255), nullable=True)
    channel_chat_id = Column(String(255), nullable=True)
    channel_type = Column(String(50), nullable=True)
    config = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<ChannelMapping(channel={self.channel}, channel_user_id={self.channel_user_id})>"


class Message(Base):
    """
    Tabla: messages

    Mensajes dentro de una sesión.
    Cada mensaje tiene role (user/assistant/system), content, y metadatos.

    Inspirado en el sistema de mensajes de Hermes Agent con FTS5 search.
    """

    __tablename__ = "messages"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    role = Column(String(20), nullable=False, doc="user, assistant, system")
    content = Column(Text, nullable=True, doc="Contenido del mensaje")
    tool_calls = Column(JSON, nullable=True, doc="Tool calls del asistente")
    tool_name = Column(String(100), nullable=True, doc="Nombre de la herramienta")
    token_count = Column(Integer, default=0)
    finish_reason = Column(String(50), nullable=True)
    reasoning = Column(Text, nullable=True, doc="Razonamiento del modelo")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<Message(role={self.role}, session={self.session_id})>"


class TenantSkill(Base):
    """
    Tabla: tenant_skills

    Skills personalizados por tenant.
    """

    __tablename__ = "tenant_skills"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), default="custom")
    version = Column(String(20), default="1.0.0")
    content = Column(Text, nullable=True)
    enabled = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<TenantSkill(name={self.name}, tenant_id={self.tenant_id})>"


class Contact(Base):
    """
    Tabla: contacts

    Contactos CRM de cada tenant.
    """

    __tablename__ = "contacts"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    channel_id = Column(String(255), nullable=True)
    channel_type = Column(String(50), nullable=True)
    tags = Column(JSON, default=list)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Contact(name={self.name}, tenant_id={self.tenant_id})>"


class WebResearchResult(Base):
    """
    Tabla: web_research_results

    Resultados de investigación web con trazabilidad completa:
    - URL consultada, fecha, contenido
    - Tenant que lo solicitó
    - Quién lo solicitó (módulo u orquestador)
    - Hash de contenido para deduplicación
    """

    __tablename__ = "web_research_results"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    url = Column(Text, nullable=False)
    title = Column(String(500), nullable=True)
    content_hash = Column(String(64), nullable=False)
    content = Column(Text, nullable=True)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, default=0)
    status_code = Column(Integer, nullable=True)
    fetch_date = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source_by = Column(String(100), nullable=False)
    task_id = Column(PG_UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<WebResearchResult(url={self.url}, tenant={self.tenant_id})>"
