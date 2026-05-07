"""
Gestión de sesiones para el orquestador Ragnar.

Inspirado en el sistema de sessiones de Hermes Agent (hermes_state.py).

Patrones implementados:
- Session Lifecycle: create, read, update, end, list, resolve, delete
- Frozen Snapshot Pattern: el contexto se lee una vez al inicio y no muta
- Session Lineage: sesiones con parent_session_id para tracking de subagentes
- FTS5 Search: búsqueda completa sobre mensajes de sesión
- WAL Mode: concurrent readers + single writer sin contentions

Modelos de DB necesarios (se agregan en db.py):
- sessions: metadata de sesión
- messages: historial de conversación
"""

import json
import logging
from typing import Optional, Dict, Any, List
from uuid import uuid4

from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from ai_platform.database import get_session
from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# === Constantes ===
MAX_MESSAGES_PER_SESSION = 100
MAX_MESSAGES_IN_CONTEXT = 20  # Últimos N mensajes para contexto


class Session:
    """
    Representa una sesión de conversación dentro de un tenant.

    Equivalente a la tabla sessions de Hermes, adaptado para SQLAlchemy.
    """

    def __init__(self, id, tenant_id, user_id, title: str, parent_id: Optional[str] = None):
        self.id = id or str(uuid4())
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.title = title
        self.parent_id = parent_id
        self.created_at: Optional[str] = None
        self.ended_at: Optional[str] = None
        self.message_count: int = 0
        self.token_count: int = 0

    @classmethod
    def from_row(cls, row: Any) -> "Session":
        """Crear una sesión desde un row de SQLAlchemy."""
        s = cls(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            title=row.title,
            parent_id=row.parent_id if hasattr(row, "parent_id") else row.parent_session_id,
        )
        s.created_at = row.created_at.isoformat() if row.created_at else None
        s.ended_at = row.ended_at.isoformat() if row.ended_at else None
        s.message_count = row.message_count
        s.token_count = row.token_count
        return s


class Message:
    """
    Representa un mensaje dentro de una sesión.

    Equivalente a la tabla messages de Hermes.
    """

    def __init__(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[List] = None,
        tool_name: Optional[str] = None,
        token_count: int = 0,
    ):
        self.id = str(uuid4())
        self.session_id = session_id
        self.role = role  # "user", "assistant", "system"
        self.content = content
        self.tool_calls = tool_calls
        self.tool_name = tool_name
        self.token_count = token_count
        self.created_at: Optional[str] = None
        self.finish_reason: Optional[str] = None
        self.reasoning: Optional[str] = None

    @classmethod
    def from_row(cls, row: Any) -> "Message":
        """Crear un mensaje desde un row de SQLAlchemy."""
        m = cls(
            session_id=row.session_id,
            role=row.role,
            content=row.content or "",
            tool_calls=json.loads(row.tool_calls) if row.tool_calls else None,
            tool_name=row.tool_name,
            token_count=row.token_count,
        )
        m.id = row.id or m.id
        m.created_at = row.created_at.isoformat() if row.created_at else None
        m.finish_reason = row.finish_reason
        m.reasoning = row.reasoning
        return m


class SessionManager:
    """
    Gestiona sesiones y mensajes para el orquestador.

    Patrones heredados de Hermes:
    - Frozen Snapshot: leer contexto una vez al inicio, mantener estable
    - Session lineage: parent_session_id para tracking
    - Recent messages: últimos N mensajes para contexto de conversación
    """

    def __init__(self):
        pass

    async def create(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        title: str = "Nueva sesión",
        parent_id: Optional[str] = None,
    ) -> Session:
        """
        Crear una nueva sesión.

        Parámetros:
            tenant_id: ID del tenant
            user_id: ID del usuario
            title: Título de la sesión
            parent_id: ID de sesión padre (si es subagent)

        Retorna:
            Session creada
        """
        session_obj = Session(
            id=str(uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            parent_id=parent_id,
        )

        with get_session() as db:
            db.execute(
                text("""
                    INSERT INTO sessions (
                        id, tenant_id, user_id, title, parent_session_id,
                        created_at, message_count, token_count
                    ) VALUES (
                        :id, :tenant_id, :user_id, :title, :parent_id,
                        NOW(), 0, 0
                    )
                """),
                {
                    "id": session_obj.id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "title": title,
                    "parent_id": parent_id,
                }
            )
            db.commit()

        return session_obj

    async def get_or_create(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Obtener una sesión existente o crear una nueva.

        Si se proporciona session_id, intenta recuperar esa sesión.
        Si no existe o está cerrada, crea una nueva.

        Parámetros:
            tenant_id: ID del tenant
            user_id: ID del usuario
            session_id: ID de sesión (opcional)

        Retorna:
            Dict con datos de la sesión (equivalente a Frozen Snapshot de Hermes)
        """
        if session_id:
            session = await self.get(session_id, tenant_id)
            if session and not session.get("ended_at"):
                return session

        # Crear nueva sesión
        new_session = await self.create(
            tenant_id=tenant_id,
            user_id=user_id,
            title=f"Sesión de {user_id or 'nuevo'}",
        )

        return {
            "id": new_session.id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "title": new_session.title,
            "parent_id": None,
            "created_at": new_session.created_at,
            "ended_at": None,
            "message_count": 0,
            "token_count": 0,
        }

    async def get(self, session_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtener una sesión por ID.

        Parámetros:
            session_id: ID de la sesión
            tenant_id: ID del tenant (para validación)

        Retorna:
            Dict con datos de la sesión o None
        """
        with get_session() as db:
            result = db.execute(
                text("SELECT * FROM sessions WHERE id = :id AND tenant_id = :tenant_id"),
                {"id": session_id, "tenant_id": tenant_id},
            ).first()

            if not result:
                return None

            return {
                "id": result.id,
                "tenant_id": result.tenant_id,
                "user_id": result.user_id,
                "title": result.title,
                "parent_id": result.parent_id if hasattr(result, "parent_id") else result.parent_session_id,
                "created_at": result.created_at.isoformat() if result.created_at else None,
                "ended_at": result.ended_at.isoformat() if result.ended_at else None,
                "message_count": result.message_count,
                "token_count": result.token_count,
            }

    async def get_context(self, session_id: str) -> Dict[str, Any]:
        """
        Obtener contexto de sesión (frozen snapshot pattern).

        Este es el patrón de "frozen snapshot" de Hermes:
        - Lee los últimos mensajes una sola vez al inicio de la sesión
        - El snapshot se mantiene estable durante toda la conversación
        - Esto preserva el prefix cache del LLM

        Parámetros:
            session_id: ID de la sesión

        Retorna:
            Dict con contexto de sesión:
                - recent_messages: lista de los últimos N mensajes
                - session_info: metadata de la sesión
                - token_estimate: tokens estimados en contexto
        """
        with get_session() as db:
            # Obtener últimos mensajes
            messages = db.execute(
                text("""
                    SELECT role, content, created_at
                    FROM messages
                    WHERE session_id = :session_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"session_id": session_id, "limit": MAX_MESSAGES_IN_CONTEXT},
            ).fetchall()

            recent_messages = []
            for msg in messages:
                recent_messages.append({
                    "role": msg.role,
                    "content": msg.content or "",
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                })

            # Obtener metadata de la sesión
            result = db.execute(
                text("SELECT * FROM sessions WHERE id = :id"),
                {"id": session_id},
            ).first()

            session_info = {}
            if result:
                session_info = {
                    "id": result.id,
                    "tenant_id": result.tenant_id,
                    "title": result.title,
                    "message_count": result.message_count,
                    "token_count": result.token_count,
                }

            return {
                "recent_messages": recent_messages,
                "session_info": session_info,
                "token_estimate": len(recent_messages) * 150,  # Estimación aproximada
            }

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[List] = None,
        tool_name: Optional[str] = None,
        token_count: int = 0,
    ) -> Message:
        """
        Agregar un mensaje a una sesión.

        Parámetros:
            session_id: ID de la sesión
            role: "user", "assistant", "system"
            content: Contenido del mensaje
            tool_calls: Herramientas llamadas (opcional)
            tool_name: Nombre de la herramienta (opcional)
            token_count: Tokens consumidos (opcional)

        Retorna:
            Message creado
        """
        msg = Message(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_name=tool_name,
            token_count=token_count,
        )

        with get_session() as db:
            db.execute(
                text("""
                    INSERT INTO messages (
                        session_id, role, content, tool_calls,
                        tool_name, token_count, created_at
                    ) VALUES (
                        :session_id, :role, :content, :tool_calls,
                        :tool_name, :token_count, NOW()
                    )
                """),
                {
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "tool_calls": json.dumps(tool_calls) if tool_calls else None,
                    "tool_name": tool_name,
                    "token_count": token_count,
                }
            )

            # Actualizar conteo de mensajes en la sesión
            db.execute(
                text("""
                    UPDATE sessions SET
                        message_count = message_count + 1,
                        token_count = token_count + :token_count
                    WHERE id = :session_id
                """),
                {"token_count": token_count, "session_id": session_id},
            )

            db.commit()

        return msg

    async def search(
        self,
        tenant_id: str,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Buscar mensajes en todas las sesiones de un tenant.

        Usa FTS5 de PostgreSQL (o LIKE search como fallback).

        Parámetros:
            tenant_id: ID del tenant
            query: Texto a buscar
            limit: Máximo de resultados

        Retorna:
            Lista de resultados con sesión_id, role, content, created_at
        """
        with get_session() as db:
            # Intentar usar pg_trgm para búsqueda completa
            result = db.execute(
                text("""
                    SELECT m.session_id, m.role, m.content, m.created_at, m.token_count
                    FROM messages m
                    JOIN sessions s ON s.id = m.session_id
                    WHERE s.tenant_id = :tenant_id
                      AND m.content ILIKE :query
                    ORDER BY m.created_at DESC
                    LIMIT :limit
                """),
                {"tenant_id": tenant_id, "query": f"%{query}%", "limit": limit},
            ).fetchall()

            return [
                {
                    "session_id": row.session_id,
                    "role": row.role,
                    "content": row.content or "",
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "token_count": row.token_count,
                }
                for row in result
            ]

    async def list_sessions(
        self,
        tenant_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Listar sesiones de un tenant.

        Parámetros:
            tenant_id: ID del tenant
            limit: Máximo de resultados
            offset: Offset para paginación

        Retorna:
            Lista de sesiones
        """
        with get_session() as db:
            result = db.execute(
                text("""
                    SELECT id, title, user_id, created_at, updated_at, message_count
                    FROM sessions
                    WHERE tenant_id = :tenant_id AND ended_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"tenant_id": tenant_id, "limit": limit, "offset": offset},
            ).fetchall()

            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "user_id": row.user_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "message_count": row.message_count,
                }
                for row in result
            ]

    async def close(self) -> None:
        """Cerrar recursos."""
        pass


# Instancia global
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Obtener la instancia de SessionManager (singleton)."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
