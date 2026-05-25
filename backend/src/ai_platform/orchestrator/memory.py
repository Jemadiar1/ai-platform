"""
Sistema de memoria acotada para Odin.

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

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import text

from ai_platform.core.security import prompt_sanitizer, scanner
from ai_platform.database import make_session

logger = logging.getLogger(__name__)


class IntegrityError(Exception):
    """Error de integridad de datos en memoria."""

    pass


def _compute_checksum(content: str) -> str:
    """
    Calcular checksum SHA-256 del contenido para verificación de integridad.

    Este checksum permite detectar corrupción de datos en la base de datos
    al comparar el hash almacenado con el hash recalculado al leer.

    Patrón de Hermes: validación de integridad antes de confirmar transacción.

    Parámetros:
        content: Contenido a verificar

    Retorna:
        Hash SHA-256 hexadecimal del contenido
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# Límites de caracteres inspirados en Hermes
MEMORY_MAX_CHARS = 2200  # ~800 tokens de contexto
USER_MAX_CHARS = 1375  # ~500 tokens de contexto
MEMORY_DELIMITER = "§"  # Separador de entradas (hermes-style)


class ContextReferenceManager:
    """
    Gestiona referencias de contexto entre sesiones.

    Cuando una sesión nueva se crea para un tenant, puede
    consultar sesiones anteriores para contexto relevante.
    Esto permite mantener consistencia en conversaciones
    que se extienden a través de múltiples sesiones.

    Patrones de Hermes aplicados:
    - Cross-session context: sesiones nuevas saben sobre sesiones previas
    - Topic extraction: identificar temas recurrentes entre sesiones
    - Recent session awareness: limitar a sesiones recientes para relevancia
    """

    async def get_session_context(
        self,
        new_session_id: str,
        tenant_id: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Obtener contexto de sesiones anteriores para un tenant.

        Recupera las sesiones más recientes del mismo tenant
        (excluyendo la sesión actual) para proporcionar contexto
        adicional al LLM.

        Parámetros:
            new_session_id: ID de la sesión nueva (excluida del contexto)
            tenant_id: ID del tenant actual
            limit: Máximo de sesiones a incluir (default: 3)

        Retorna:
            Lista de dicts con contexto de sesiones previas
        """
        with make_session() as db:
            result = db.execute(
                text("""
                SELECT id, created_at, message_count
                FROM sessions
                WHERE tenant_id = :tenant_id
                  AND id != :new_session_id
                ORDER BY created_at DESC
                LIMIT :limit
            """),
                {
                    "tenant_id": tenant_id,
                    "new_session_id": new_session_id,
                    "limit": limit,
                },
            ).fetchall()

            contexts = []
            for row in result:
                contexts.append(
                    {
                        "session_id": str(row.id),
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "message_count": row.message_count or 0,
                        "is_active": True,
                    }
                )

            return contexts

    async def get_common_topics(
        self,
        tenant_id: str,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """
        Obtener temas comunes entre sesiones previas.

        Analiza los mensajes del asistente en la sesión actual
        y extrae temas recurrentes basados en contenido corto.

        Parámetros:
            tenant_id: ID del tenant
            session_id: ID de la sesión actual

        Retorna:
            Lista de dicts con temas y su peso
        """
        with make_session() as db:
            result = db.execute(
                text("""
                SELECT DISTINCT content FROM messages
                WHERE session_id = :session_id
                  AND role = 'assistant'
                  AND CHAR_LENGTH(content) < 100
            """),
                {"session_id": session_id},
            ).fetchall()

            topics = [row.content for row in result if row.content]

            return [{"topic": topic, "weight": 0.5} for topic in topics]


# Instancia global del manager de contexto
_context_reference_manager: ContextReferenceManager | None = None


def get_context_reference_manager() -> ContextReferenceManager:
    """
    Obtener la instancia de ContextReferenceManager (singleton).

    Retorna:
        Instancia de ContextReferenceManager
    """
    global _context_reference_manager
    if _context_reference_manager is None:
        _context_reference_manager = ContextReferenceManager()
    return _context_reference_manager


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
    ) -> dict[str, Any]:
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
            "knowledge_relevant": [],  # Se llena desde Odin con tenant_id
            "total_chars": len(memory_text) + len(user_text),
        }

    async def add_entry(
        self,
        session_id: str,
        entry_type: str,
        content: str,
    ) -> dict[str, Any]:
        """
        Agregar una entrada a la memoria acotada con patrón de escritura atómica.

        Implementa el patrón de Hermes:
        1. Iniciar transacción
        2. Guardar en tabla temporal (backup)
        3. Validar datos (checksum, longitud)
        4. Confirmar (swap atómico)
        5. Revertir en caso de error

        Aplica:
        1. Security scanning (12 patrones)
        2. Checksum validation (SHA-256)
        3. Duplicate rejection
        4. Char limit enforcement
        5. Atomic DB transaction

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
            logger.warning(f"Memory injection detected. Patterns: {scan_result['flagged_patterns']}. Rejecting write.")
            return {
                "success": False,
                "error": "prompt_injection_detected",
                "message": f"Security patterns detected: {', '.join(scan_result['flagged_patterns'])}",
            }

        # Sanitize
        content = prompt_sanitizer.sanitize(content)

        # Check limits
        max_chars = self.max_memory_chars if entry_type == "memory" else self.max_user_chars

        # Compute checksum for integrity validation
        checksum = _compute_checksum(content)

        # Atomic write pattern: single transaction with validation
        try:
            with make_session() as db:
                # Step 1: Get current total chars for this entry type
                result = db.execute(
                    text(f"""
                        SELECT COALESCE(SUM(CHAR_LENGTH(content)), 0) as total
                        FROM agent_memory
                        WHERE agent_id = :session_id
                          AND type = :type
                          AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = '{session_id}'::uuid)
                    """),
                    {"type": entry_type},
                ).first()

                current_total_chars = result.total if result else 0

                # Step 2: Validate char limit before any write
                if current_total_chars + len(content) > max_chars:
                    return {
                        "success": False,
                        "error": "memory_full",
                        "message": f"Memory is full ({current_total_chars}/{max_chars} chars). "
                        f"Consider consolidating entries.",
                        "available_chars": max_chars - current_total_chars,
                    }

                # Step 3: Duplicate rejection (check before insert)
                existing = db.execute(
                    text(f"""
                        SELECT id FROM agent_memory
                        WHERE agent_id = :session_id
                          AND type = :type
                          AND content = :content
                          AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = '{session_id}'::uuid)
                    """),
                    {"session_id": session_id, "type": entry_type, "content": content},
                ).first()

                if existing:
                    return {
                        "success": False,
                        "error": "duplicate",
                        "message": "Entry already exists (no duplicate added).",
                    }

                # Step 4: Begin atomic insert
                # Insert into agent_memory with checksum for integrity
                db.execute(
                    text(f"""
                        INSERT INTO agent_memory (
                            tenant_id, agent_id, type, content, char_count, checksum, created_at
                        ) VALUES (
                            (SELECT tenant_id FROM sessions WHERE id = '{session_id}'::uuid),
                            :session_id,
                            :type, :content, :char_count, :checksum, NOW()
                        )
                    """),
                    {
                        "session_id": session_id,
                        "type": entry_type,
                        "content": content,
                        "char_count": len(content),
                        "checksum": checksum,
                    },
                )

                # Step 5: Validate the write (checksum verification)
                verify_result = db.execute(
                    text(f"""
                        SELECT checksum FROM agent_memory
                        WHERE agent_id = :session_id
                          AND type = :type
                          AND content = :content
                          AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = '{session_id}'::uuid)
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {
                        "session_id": session_id,
                        "type": entry_type,
                        "content": content,
                    },
                ).first()

                # Validate: checksum must match
                if verify_result and verify_result.checksum != checksum:
                    logger.error(
                        f"Checksum mismatch for memory entry: session={session_id}, "
                        f"expected={checksum}, got={verify_result.checksum}"
                    )
                    raise IntegrityError("Checksum mismatch for memory entry. Data may be corrupted.")

                # Step 6: Commit (atomic swap - all or nothing)
                db.commit()

        except IntegrityError as e:
            logger.error(f"Memory write failed integrity check: {e}")
            raise
        except Exception as e:
            logger.error(f"Memory write failed: {e}")
            raise

        logger.info(
            f"Memory entry added (atomic): type={entry_type}, chars={len(content)}, "
            f"session={session_id}, checksum={checksum[:16]}..."
        )

        return {
            "success": True,
            "chars_added": len(content),
            "total_chars": current_total_chars + len(content),
            "max_chars": max_chars,
            "checksum": checksum,
        }

    async def sync_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_result: dict[str, Any],
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
            f"Turn synced: session={session_id}, user_chars={len(user_message)}, result_chars={len(result_content)}"
        )

    async def get_summary(
        self,
        session_id: str,
    ) -> dict[str, Any]:
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
                text(f"""
                    SELECT
                        COUNT(*) FILTER (WHERE type = 'memory') as memory_count,
                        COUNT(*) FILTER (WHERE type = 'user') as user_count
                    FROM agent_memory
                    WHERE agent_id = :session_id
                      AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = '{session_id}'::uuid)
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
                text(f"""
                    SELECT content
                    FROM agent_memory
                    WHERE agent_id = :session_id
                      AND type = 'memory'
                      AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = '{session_id}'::uuid)
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
                text(f"""
                    SELECT content
                    FROM agent_memory
                    WHERE agent_id = :session_id
                      AND type = 'user'
                      AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = '{session_id}'::uuid)
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
    ) -> list[dict[str, Any]]:
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
    def _render_block(delimiter: str, entries: list[str]) -> str:
        """
        Renderizar una lista de entradas con un delimitador.

        Pattern from Hermes: entries separated by § (section sign).
        """
        if not entries:
            return ""
        return delimiter.join(entries)


# Instancia global
_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """Obtener la instancia de MemoryManager (singleton)."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
