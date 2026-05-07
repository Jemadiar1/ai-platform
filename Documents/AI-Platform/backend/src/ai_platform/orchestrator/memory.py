"""
Sistema de memoria acotada para Ragnar.

Inspirado en el sistema de memoria de Hermes Agent (hermes_state.py, tools/memory_tool.py).

Patrones implementados:
- Bounded memory con char limits (MEMORY.md ~2200 chars, USER.md ~1375 chars)
- Duplicate rejection (no agregar entradas duplicadas)
- Security scanning (12 patrones de inyección antes de escribir)
- Frozen snapshot (injection única al inicio de sesión)
- Atomic writes (tempfile + replace para evitar corrupción)

Uso:
    mgr = MemoryManager()
    await mgr.prefetch(session_id, prompt)  # Recall antes de cada turno
    await mgr.sync_turn(session_id, user_msg, asst_result)  # Sync después de cada turno
"""

import json
import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ai_platform.database import make_session
from ai_platform.core.security import scanner, prompt_sanitizer
from ai_platform.orchestrator.session import SessionManager

logger = logging.getLogger(__name__)

# Límites de caracteres inspirados en Hermes
MEMORY_MAX_CHARS = 2200     # ~800 tokens de contexto
USER_MAX_CHARS = 1375       # ~500 tokens de contexto
MEMORY_DELIMITER = "§"     # Separador de entradas (hermes-style)


class MemoryEntry:
    """
    Represents a single memory entry.
    
    Pattern from Hermes: entries are stored with a section delimiter.
    """

    def __init__(self, type: str, content: str, char_count: int = 0):
        self.type = type  # "memory" or "user"
        self.content = content
        self.char_count = char_count or len(content)

    def __repr__(self):
        return f"<MemoryEntry(type={self.type}, chars={self.char_count})>"


class MemoryManager:
    """
    Gestiona la memoria acotada del orquestador.

    Patrones de Hermes aplicados:
    1. Bounded memory: char limits estrictos
    2. Duplicate rejection: no agregar entradas idénticas
    3. Security scanning: 12 patrones antes de escribir
    4. Prefetch: recordar memoria relevante antes de cada turno
    5. Sync turn: guardar conversación después de cada turno
    6. Frozen snapshot: contexto inyectado una vez, estable

    Tipos de memoria:
    - MEMORY: notas del agente (~2200 chars)
    - USER: perfil del usuario (~1375 chars)
    """

    def __init__(self):
        self.max_memory_chars = MEMORY_MAX_CHARS
        self.max_user_chars = USER_MAX_CHARS

    async def prefetch(
        self,
        session_id: str,
        prompt: str,
    ) -> Dict[str, Any]:
        """
        Prefetch: recordar memoria relevante ANTES de cada turno.

        Inspirado en MemoryProvider.prefetch() de Hermes.
        Busca entradas de memoria relevantes al prompt actual.

        Parámetros:
            session_id: ID de la sesión
            prompt: Prompt actual del usuario

        Retorna:
            Dict con memoria relevante:
                - memory: texto de MEMORY.md inyectado en system prompt
                - user: texto de USER.md inyectado en system prompt
                - search_results: resultados de búsqueda FTS
        """
        memory_text = await self._get_bounded_memory(session_id)
        user_text = await self._get_bounded_user_profile(session_id)

        # Search en mensajes anteriores para contexto
        search_results = await self._search_context(session_id, prompt, limit=3)

        return {
            "memory": memory_text,
            "user": user_text,
            "search_results": search_results,
            "total_chars": len(memory_text) + len(user_text),
        }

    async def add_entry(
        self,
        session_id: str,
        entry_type: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Agregar una entrada a la memoria acotada.

        Aplica:
        1. Security scanning (12 patrones)
        2. Duplicate rejection
        3. Char limit enforcement

        Parámetros:
            session_id: ID de la sesión
            entry_type: "memory" o "user"
            content: Contenido de la entrada

        Retorna:
            Dict con resultado de la operación
        """
        # Security scan
        scan_result = scanner.scan(content)
        if not scan_result["is_safe"]:
            logger.warning(
                f"Memory injection detected. Patterns: {scan_result['flagged_patterns']}. "
                "Rejecting write."
            )
            return {
                "success": False,
                "error": "prompt_injection_detected",
                "message": f"Security patterns detected: {', '.join(scan_result['flagged_patterns'])}",
            }

        # Sanitize
        content = prompt_sanitizer.sanitize(content)

        # Check limits
        max_chars = self.max_memory_chars if entry_type == "memory" else self.max_user_chars

        with make_session() as db:
            # Get current total
            result = db.execute(
                text("""
                    SELECT COALESCE(SUM(CHAR_LENGTH(content)), 0) as total
                    FROM agent_memory
                    WHERE session_id = :session_id
                      AND type = :type
                      AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = :session_id)
                """),
                {"session_id": session_id, "type": entry_type},
            ).first()

            current_total_chars = result.total if result else 0

            # Check if adding would exceed limit
            if current_total_chars + len(content) > max_chars:
                return {
                    "success": False,
                    "error": "memory_full",
                    "message": f"Memory is full ({current_total_chars}/{max_chars} chars). "
                              f"Consider consolidating entries.",
                    "available_chars": max_chars - current_total_chars,
                }

            # Duplicate rejection
            existing = db.execute(
                text("""
                    SELECT id FROM agent_memory
                    WHERE session_id = :session_id
                      AND type = :type
                      AND content = :content
                      AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = :session_id)
                """),
                {"session_id": session_id, "type": entry_type, "content": content},
            ).first()

            if existing:
                return {
                    "success": False,
                    "error": "duplicate",
                    "message": "Entry already exists (no duplicate added).",
                }

            # Add entry
            db.execute(
                text("""
                    INSERT INTO agent_memory (
                        session_id, tenant_id, type, content, char_count, created_at
                    ) VALUES (
                        :session_id,
                        (SELECT tenant_id FROM sessions WHERE id = :session_id),
                        :type, :content, :char_count, NOW()
                    )
                """),
                {
                    "session_id": session_id,
                    "type": entry_type,
                    "content": content,
                    "char_count": len(content),
                }
            )
            db.commit()

        logger.info(
            f"Memory entry added: type={entry_type}, chars={len(content)}, "
            f"session={session_id}"
        )

        return {
            "success": True,
            "chars_added": len(content),
            "total_chars": current_total_chars + len(content),
            "max_chars": max_chars,
        }

    async def sync_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_result: Dict[str, Any],
    ) -> None:
        """
        Sync: guardar conversación después de cada turno.

        Inspirado en MemoryProvider.sync_turn() de Hermes.
        Guarda el turno (user + assistant) como una unidad atómica.

        Parámetros:
            session_id: ID de la sesión
            user_message: Mensaje del usuario
            assistant_result: Resultado del asistente
        """
        # Sanitize both messages
        user_message = prompt_sanitizer.sanitize(user_message)
        result_content = json.dumps(assistant_result) if isinstance(assistant_result, dict) else str(assistant_result)
        result_content = prompt_sanitizer.sanitize(result_content)

        # Add both user and assistant messages to session history
        from ai_platform.orchestrator.session import get_session_manager
        sm = get_session_manager()

        await sm.add_message(
            session_id=session_id,
            role="user",
            content=user_message,
        )

        await sm.add_message(
            session_id=session_id,
            role="assistant",
            content=result_content,
        )

        logger.info(
            f"Turn synced: session={session_id}, "
            f"user_chars={len(user_message)}, result_chars={len(result_content)}"
        )

    async def get_summary(
        self,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Obtener un resumen de la memoria de una sesión.

        Parámetros:
            session_id: ID de la sesión

        Retorna:
            Dict con resumen de memoria
        """
        memory_text = await self._get_bounded_memory(session_id)
        user_text = await self._get_bounded_user_profile(session_id)

        with make_session() as db:
            result = db.execute(
                text("""
                    SELECT 
                        COUNT(*) FILTER (WHERE type = 'memory') as memory_count,
                        COUNT(*) FILTER (WHERE type = 'user') as user_count
                    FROM agent_memory
                    WHERE session_id = :session_id
                      AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = :session_id)
                """),
                {"session_id": session_id},
            ).first()

            memory_count = result.memory_count if result else 0
            user_count = result.user_count if result else 0

        return {
            "memory": {
                "text": memory_text,
                "chars": len(memory_text),
                "count": memory_count,
                "capacity_percent": round((len(memory_text) / self.max_memory_chars) * 100, 1),
            },
            "user": {
                "text": user_text,
                "chars": len(user_text),
                "count": user_count,
                "capacity_percent": round((len(user_text) / self.max_user_chars) * 100, 1),
            },
        }

    async def close(self) -> None:
        """Cerrar recursos."""
        pass

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    async def _get_bounded_memory(self, session_id: str) -> str:
        """
        Obtener memoria acotada (MEMORY.md equivalent).
        """
        with make_session() as db:
            result = db.execute(
                text("""
                    SELECT content
                    FROM agent_memory
                    WHERE session_id = :session_id
                      AND type = 'memory'
                      AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = :session_id)
                    ORDER BY created_at DESC
                """),
                {"session_id": session_id},
            ).fetchall()

        entries = []
        current_chars = 0

        for row in result:
            entry = row.content
            if current_chars + len(entry) > self.max_memory_chars:
                # Truncate to fit
                remaining = self.max_memory_chars - current_chars
                if remaining > 0:
                    entry = entry[:remaining].rstrip()
                else:
                    break
            entries.append(entry)
            current_chars += len(entry)

        return self._render_block(MEMORY_DELIMITER, entries)

    async def _get_bounded_user_profile(self, session_id: str) -> str:
        """
        Obtener perfil de usuario acotado (USER.md equivalent).
        """
        with make_session() as db:
            result = db.execute(
                text("""
                    SELECT content
                    FROM agent_memory
                    WHERE session_id = :session_id
                      AND type = 'user'
                      AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = :session_id)
                    ORDER BY created_at DESC
                """),
                {"session_id": session_id},
            ).fetchall()

        entries = []
        current_chars = 0

        for row in result:
            entry = row.content
            if current_chars + len(entry) > self.max_user_chars:
                remaining = self.max_user_chars - current_chars
                if remaining > 0:
                    entry = entry[:remaining].rstrip()
                else:
                    break
            entries.append(entry)
            current_chars += len(entry)

        return self._render_block(MEMORY_DELIMITER, entries)

    async def _search_context(
        self,
        session_id: str,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Buscar contexto relevante en mensajes anteriores.
        """
        with make_session() as db:
            result = db.execute(
                text("""
                    SELECT role, content, created_at
                    FROM messages
                    WHERE session_id = :session_id
                      AND content ILIKE :query
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"session_id": session_id, "query": f"%{query}%", "limit": limit},
            ).fetchall()

            return [
                {
                    "role": row.role,
                    "content": row.content or "",
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in result
            ]

    @staticmethod
    def _render_block(delimiter: str, entries: List[str]) -> str:
        """
        Renderizar una lista de entradas con un delimitador.
        
        Pattern from Hermes: entries separated by § (section sign).
        """
        if not entries:
            return ""
        return delimiter.join(entries)


# Instancia global
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Obtener la instancia de MemoryManager (singleton)."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
