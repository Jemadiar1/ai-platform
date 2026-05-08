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
import threading
from typing import Optional, Dict, Any, List

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ai_platform.database import make_session
from ai_platform.core.security import scanner, prompt_sanitizer
from ai_platform.orchestrator.session import SessionManager
from ai_platform.orchestrator.llm_client import ROUTING_MODELS

logger = logging.getLogger(__name__)

# Límites de caracteres inspirados en Hermes
MEMORY_MAX_CHARS = 2200     # ~800 tokens de contexto
USER_MAX_CHARS = 1375       # ~500 tokens de contexto
MEMORY_DELIMITER = "§"     # Separador de entradas (hermes-style)


class MemoryEntry:
    """
    Representa una entrada individual de memoria.

    Patrón heredado de Hermes: las entradas se almacenan con un delimitador de sección.
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

    # Umbral mínimo de repeticiones para considerar un patrón como skill
    ACTION_REPETITION_THRESHOLD = 3

    def __init__(self):
        self.max_memory_chars = MEMORY_MAX_CHARS
        self.max_user_chars = USER_MAX_CHARS
        # Lock para operaciones thread-safe en _action_tracker
        self._lock = threading.Lock()
        # Cache en memoria para tracking de acciones por sesión (se reinicia con cada instancia)
        # key: session_id -> value: {action_type -> count}
        self._action_tracker: Dict[str, Dict[str, int]] = {}

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

        # Búsqueda en mensajes anteriores para contexto
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
                f"Se detectó inyección en memoria. Patrones: {scan_result['flagged_patterns']}. "
                "Rechazando escritura."
            )
            return {
                "success": False,
                "error": "prompt_injection_detected",
                "message": f"Se detectaron patrones de seguridad: {', '.join(scan_result['flagged_patterns'])}",
            }

        # Sanitize
        content = prompt_sanitizer.sanitize(content)

        # Check limits
        max_chars = self.max_memory_chars if entry_type == "memory" else self.max_user_chars

        with make_session() as db:
            # Get current total
            # agent_memory no tiene session_id aún, usamos agent_id como referencia
            result = db.execute(
                text("""
                    SELECT COALESCE(SUM(CHAR_LENGTH(content)), 0) as total
                    FROM agent_memory
                    WHERE agent_id = :session_id
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
                    "error": "memoria_llena",
                    "message": f"La memoria está llena ({current_total_chars}/{max_chars} caracteres). "
                              f"Considere consolidar las entradas.",
                    "available_chars": max_chars - current_total_chars,
                }

            # Duplicate rejection
            existing = db.execute(
                text("""
                    SELECT id FROM agent_memory
                    WHERE agent_id = :session_id
                      AND type = :type
                      AND content = :content
                      AND tenant_id = (SELECT tenant_id FROM sessions WHERE id = :session_id)
                """),
                {"session_id": session_id, "type": entry_type, "content": content},
            ).first()

            if existing:
                return {
                    "success": False,
                    "error": "duplicado",
                    "message": "La entrada ya existe (no se agregó duplicado).",
                }

            # Add entry
            db.execute(
                text("""
                    INSERT INTO agent_memory (
                        tenant_id, agent_id, type, content, char_count, created_at
                    ) VALUES (
                        (SELECT tenant_id FROM sessions WHERE id = :session_id),
                        :session_id,
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
            f"Entrada de memoria agregada: type={entry_type}, chars={len(content)}, "
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
    ) -> Dict[str, Any]:
        """
        Sync: guardar conversación después de cada turno.

        Inspirado en MemoryProvider.sync_turn() de Hermes.
        Guarda el turno (user + assistant) como una unidad atómica.
        
        Después de guardar el turno, analiza si el usuario está exhibiendo
        un patrón repetible (misma acción 3+ veces) para auto-crear un skill.

        Parámetros:
            session_id: ID de la sesión
            user_message: Mensaje del usuario
            assistant_result: Resultado del asistente

        Retorna:
            Dict con resultado del sync:
                - synced: bool
                - session_id: str
                - user_chars: int
                - result_chars: int
                - auto_discovered_skill: dict o None
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
            f"Turno sincronizado: session={session_id}, "
            f"user_chars={len(user_message)}, result_chars={len(result_content)}"
        )

        # ----------------------------------------------------------------
        # Auto-skill creation: analizar patrones repetidos del usuario
        # ----------------------------------------------------------------
        auto_discovered = await self._detect_and_create_skill(
            session_id=session_id,
            user_message=user_message,
            assistant_result=assistant_result,
        )

        return {
            "synced": True,
            "session_id": session_id,
            "user_chars": len(user_message),
            "result_chars": len(result_content),
            "auto_discovered_skill": auto_discovered,
        }

    async def _detect_and_create_skill(
        self,
        session_id: str,
        user_message: str,
        assistant_result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Detectar patrones repetidos del usuario y auto-crear un skill.

        Flujo:
        1. Analizar el mensaje del usuario para extraer el tipo de acción
        2. Incrementar contador de esa acción para la sesión
        3. Si se alcanza el umbral (3+ repeticiones), llamar al LLM
        4. El LLM extrae nombre y descripción del skill
        5. Se registra el skill con categoría "learned" y enabled=False
        6. Se loguea para revisión de admin

        Parámetros:
            session_id: ID de la sesión
            user_message: Mensaje del usuario
            assistant_result: Resultado del asistente

        Retorna:
            Dict con info del skill auto-descubierto o None
        """
        # Extraer tipo de acción del mensaje del usuario
        action_type = self._extract_action_type(user_message)
        if not action_type:
            return None

        # Acceso thread-safe al tracker con lock
        with self._lock:
            if session_id not in self._action_tracker:
                self._action_tracker[session_id] = {}

            tracker = self._action_tracker[session_id]
            tracker[action_type] = tracker.get(action_type, 0) + 1
            count = tracker[action_type]

            # Eviccionar sesiones antiguas si se excede el límite
            if len(self._action_tracker) > 1000:
                keys_to_remove = list(self._action_tracker.keys())[:-500]
                for k in keys_to_remove:
                    del self._action_tracker[k]

        # Si no alcanzó el umbral, no hacer nada
        if count < self.ACTION_REPETITION_THRESHOLD:
            logger.debug(
                f"Acción '{action_type}' repetida {count}/{self.ACTION_REPETITION_THRESHOLD} veces en sesión {session_id}"
            )
            return None

        # Umbral alcanzado: intentar auto-crear skill
        logger.info(
            f"Patrón detectado: acción '{action_type}' repetida {count} veces en sesión {session_id}. "
            "Intentando auto-crear skill..."
        )

        # Obtener tenant_id de la sesión para registrar el skill
        tenant_id = await self._get_session_tenant_id(session_id)
        if not tenant_id:
            logger.warning(f"No se pudo obtener tenant_id para sesión {session_id}, saltando auto-skill")
            return None

        try:
            from ai_platform.orchestrator.skills import get_skill_manager
            skill_mgr = get_skill_manager()

            # Construir prompt para el LLM con contexto de las interacciones
            interaction_context = self._build_action_context(session_id, action_type)

            skill_prompt = (
                "Eres un asistente de análisis de patrones de habilidades.\n\n"
                "Un usuario ha repetido la misma acción "
                f"{count} veces en una sesión: '{action_type}'.\n"
                f"Contexto de interacciones:\n{interaction_context}\n\n"
                "Determina si vale la pena crear un skill reutilizable.\n\n"
                "Responde SIEMPRE en este formato JSON:\n"
                "{\n"
                '  "should_create": true/false,\n'
                '  "skill_name": "nombre_en_mayusculas_snake_case", (solo si should_create=true)\n'
                '  "skill_description": "breve descripción de lo que hace el skill", (solo si should_create=true)\n'
                '  "trigger_pattern": "descripción del patrón que activa el skill", (solo si should_create=true)\n'
                "}\n\n"
                "Solo crea un skill si la acción es compleja y reutilizable.\n"
                "No crees un skill para acciones simples como saludar o preguntar el clima."
            )

            response = await self._call_skill_llm(skill_prompt)
            if not response:
                return None

            should_create = response.get("should_create", False)
            if not should_create:
                logger.info("LLM decidió no crear un skill para este patrón")
                return None

            skill_name = response.get("skill_name", "").strip().lower()
            skill_description = response.get("skill_description", "").strip()
            trigger_pattern = response.get("trigger_pattern", action_type)

            if not skill_name or not skill_description:
                logger.info("LLM devolvió datos incompletos, saltando")
                return None

            # Sanitizar nombre del skill
            import re
            skill_name = re.sub(r"[^a-z0-9_]", "_", skill_name)
            skill_name = re.sub(r"_+", "_", skill_name).strip("_")

            # Registrar el skill
            auto_skill_info = await skill_mgr._auto_create_learned_skill(
                tenant_id=tenant_id,
                skill_name=skill_name,
                skill_description=skill_description,
                trigger_pattern=trigger_pattern,
                action_type=action_type,
                repetition_count=count,
            )

            if auto_skill_info:
                logger.info(
                    f"Skill auto-descubierto: name='{skill_name}', "
                    f"description='{skill_description[:80]}', "
                    f"repetitions={count}, tenant={tenant_id}"
                )

            return auto_skill_info

        except Exception as e:
            logger.warning(f"Error auto-creando skill para tenant {tenant_id}: {e}")
            return None

    def _extract_action_type(self, message: str) -> Optional[str]:
        """
        Extraer el tipo de acción de un mensaje del usuario.

        Analiza palabras clave para clasificar la intención del usuario
        en categorías de acción reutilizables.

        Parámetros:
            message: Mensaje del usuario

        Retorna:
            Nombre de la acción o None si no se puede determinar
        """
        message_lower = message.lower().strip()

        # Reglas de extracción de acción basadas en palabras clave
        action_keywords = {
            "send_whatsapp": [
                "enviar whatsapp", "enviar mensaje whatsapp", "whatsapp a",
                "mandar whatsapp", "enviar por whatsapp",
            ],
            "send_telegram": [
                "enviar telegram", "telegram a", "mandar telegram",
                "enviar por telegram",
            ],
            "generate_article": [
                "generar artículo", "escribir blog", "crear article",
                "escribir un post", "generar blog",
            ],
            "generate_copy": [
                "generar copy", "crear copy", "escribir copy",
                "generar texto publicitario",
            ],
            "generate_post": [
                "crear post", "generar post", "publicar en",
                "post para instagram", "post para facebook",
            ],
            "schedule_post": [
                "programar post", "programar publicación",
                "programar para", "agendar post",
            ],
            "make_voice_call": [
                "llamar por voz", "hacer llamada", "llamada de voz",
                "llamar al", "voice call",
            ],
            "schedule_appointment": [
                "agendar cita", "programar cita", "reservar cita",
                "agendar reunión", "programar reunión",
            ],
            "generate_leads": [
                "generar leads", "buscar leads", "encontrar leads",
                "prospectar", "generar prospectos",
            ],
            "analyze_performance": [
                "analizar rendimiento", "ver métricas", "ver estadísticas",
                "reporte de", "análisis de",
            ],
            "create_campaign": [
                "crear campaña", "crear anuncio", "campaign para",
                "publicidad en", "ads para",
            ],
            "generate_page": [
                "crear landing", "crear página", "generar página web",
                "landing page", "generar web",
            ],
            "update_contact": [
                "actualizar contacto", "editar contacto", "modificar contacto",
            ],
            "get_contacts": [
                "ver contactos", "listar contactos", "buscar contactos",
                "mis contactos",
            ],
        }

        for action, keywords in action_keywords.items():
            for keyword in keywords:
                if keyword in message_lower:
                    return action

        return None

    def _build_action_context(self, session_id: str, action_type: str) -> str:
        """
        Construir contexto de interacciones para el prompt del LLM.

        Recupera los últimos mensajes de la sesión que coinciden
        con el tipo de acción detectado.

        Parámetros:
            session_id: ID de la sesión
            action_type: Tipo de acción detectado

        Retorna:
            String con contexto formateado
        """
        try:
            with make_session() as db:
                result = db.execute(
                    text("""
                        SELECT role, content, created_at
                        FROM messages
                        WHERE session_id = :session_id
                        ORDER BY created_at DESC
                        LIMIT 10
                    """),
                    {"session_id": session_id},
                ).fetchall()

                if not result:
                    return "No hay mensajes previos en la sesión."

                context_lines = []
                for row in result:
                    role = row.role
                    content = row.content or ""
                    created = row.created_at.isoformat() if row.created_at else "unknown"
                    context_lines.append(f"[{created}] {role}: {content[:200]}")

                return "\n".join(context_lines)

        except Exception as e:
            logger.warning(f"Error obteniendo contexto de sesión {session_id}: {e}")
            return f"Error obteniendo contexto: {e}"

    async def _call_skill_llm(self, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Llamar al LLM para análisis de auto-skill.

        Parámetros:
            prompt: Prompt para el LLM

        Retorna:
            Dict con la respuesta parseada o None
        """
        try:
            from ai_platform.orchestrator.llm_client import LLMClient
            llm = LLMClient()
        except RuntimeError:
            logger.info("LLM no disponible, saltando auto-skill creation")
            return None

        try:
            response = await llm.client.post(
                "/v1/chat/completions",
                json={
                    "model": ROUTING_MODELS["fast"],
                    "messages": [
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 512,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )

            if response.status_code != 200:
                logger.info(f"La llamada al LLM falló para auto-skill (status {response.status_code})")
                return None

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)

        except Exception as e:
            logger.warning(f"Error al llamar al LLM para auto-skill: {e}")
            return None

    async def _get_session_tenant_id(self, session_id: str) -> Optional[str]:
        """
        Obtener el tenant_id de una sesión.

        Parámetros:
            session_id: ID de la sesión

        Retorna:
            UUID del tenant como string o None
        """
        try:
            with make_session() as db:
                result = db.execute(
                    text("""
                        SELECT tenant_id FROM sessions WHERE id = :session_id
                    """),
                    {"session_id": session_id},
                ).first()

                if result:
                    return str(result.tenant_id)
                return None
        except Exception as e:
            logger.warning(f"Error obteniendo tenant_id para sesión {session_id}: {e}")
            return None

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
                    WHERE agent_id = :session_id
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
                    WHERE agent_id = :session_id
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
                    WHERE agent_id = :session_id
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

        Patrón heredado de Hermes: entradas separadas por § (signo de sección).
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
