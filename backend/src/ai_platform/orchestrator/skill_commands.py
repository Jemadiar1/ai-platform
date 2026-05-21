"""
Sistema de comandos del agente (skill commands).

Implementa comandos tipo /command que el usuario puede invocar
para controlar el comportamiento del agente, similar a:
- /help - Mostrar ayuda
- /reset - Resetear conversación
- /memory - Ver estado de memoria
- /budget - Ver presupuesto usado
- /skills - Ver skills disponibles
- /model - Cambiar modelo LLM
- /clear - Limpiar historial
- /summarize - Resumir sesión
- /export - Exportar conversación
- /import - Importar conversación

Inspirado en el command system de Hermes Agent.

Patrones implementados:
- Comandos con handler registrado
- Cooldown entre ejecuciones
- Verificación de autenticación
- Gestión centralizada de comandos
- Extensibilidad (nuevos comandos registrados dinámicamente)
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SkillCommand:
    """
    Comando disponible para el usuario.

    Cada comando tiene:
    - Nombre: identificador único (ej: "help")
    - Descripción: para mostrar en /help
    - Handler: función asíncrona que ejecuta la lógica
    - Cooldown: tiempo mínimo entre ejecuciones (segundos)
    - Requires auth: si necesita tenant válido
    - Last used: timestamp del último uso
    """

    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable,
        cooldown_seconds: int = 0,
        requires_auth: bool = True,
    ):
        self.name = name
        self.description = description
        self.handler = handler
        self.cooldown_seconds = cooldown_seconds
        self.requires_auth = requires_auth
        self.last_used: datetime | None = None

    def can_execute(self, tenant_id: str) -> bool:
        """
        Verificar si el comando puede ejecutarse ahora.

        Comprueba dos condiciones:
        1. Si requiere autenticación y no tiene tenant_id
        2. Si está en cooldown respecto al último uso

        Parámetros:
            tenant_id: ID del tenant actual

        Retorna:
            True si el comando puede ejecutarse
        """
        if not self.requires_auth:
            return True
        if self.cooldown_seconds > 0 and self.last_used:
            elapsed = (datetime.now() - self.last_used).total_seconds()
            if elapsed < self.cooldown_seconds:
                return False
        return True

    def mark_used(self):
        """Marcar comando como usado (actualizar timestamp)."""
        self.last_used = datetime.now()


class SkillCommandManager:
    """
    Gestiona todos los comandos disponibles.

    Patrón singleton con registro dinámico de comandos.
    Los comandos se registran automáticamente al crear la instancia.

    Uso:
        mgr = get_skill_command_manager()
        result = await mgr.execute("help", {}, tenant_id, session_id)
        commands = mgr.list_all()
    """

    def __init__(self):
        self._commands: dict[str, SkillCommand] = {}
        self._register_builtins()

    def _register_builtins(self):
        """
        Registrar todos los comandos por defecto.

        Estos comandos están siempre disponibles:
        - help: Muestra ayuda
        - reset: Resetea conversación
        - memory: Estado de memoria
        - budget: Presupuesto usado
        - skills: Skills disponibles
        - model: Cambiar modelo LLM
        - clear: Limpiar historial
        - summarize: Resumir sesión
        - export: Exportar conversación
        - import: Importar conversación
        - status: Estado del sistema
        """
        self.register(
            "help",
            "Muestra esta ayuda",
            self._cmd_help,
            requires_auth=False,
        )
        self.register(
            "reset",
            "Resetea la conversación actual",
            self._cmd_reset,
            cooldown_seconds=10,
        )
        self.register(
            "memory",
            "Muestra el estado de la memoria",
            self._cmd_memory,
            cooldown_seconds=5,
        )
        self.register(
            "budget",
            "Muestra el presupuesto usado",
            self._cmd_budget,
            cooldown_seconds=5,
        )
        self.register(
            "skills",
            "Muestra skills disponibles",
            self._cmd_skills,
            requires_auth=False,
        )
        self.register(
            "model",
            "Cambia el modelo LLM (list|set <model>)",
            self._cmd_model,
            cooldown_seconds=15,
        )
        self.register(
            "clear",
            "Limpia el historial de mensajes",
            self._cmd_clear,
            cooldown_seconds=10,
        )
        self.register(
            "summarize",
            "Genera un resumen de la sesión",
            self._cmd_summarize,
            cooldown_seconds=30,
        )
        self.register(
            "export",
            "Exporta la conversación actual",
            self._cmd_export,
            cooldown_seconds=10,
        )
        self.register(
            "import",
            "Importa una conversación guardada",
            self._cmd_import,
            cooldown_seconds=10,
        )
        self.register(
            "status",
            "Muestra el estado del sistema",
            self._cmd_status,
            requires_auth=False,
        )

    def register(
        self,
        name: str,
        description: str,
        handler: Callable,
        cooldown_seconds: int = 0,
        requires_auth: bool = True,
    ):
        """
        Registrar un nuevo comando.

        Permite extender el sistema de comandos con comandos personalizados.
        Si ya existe un comando con ese nombre, se sobrescribe.

        Parámetros:
            name: Nombre del comando (sin slash)
            description: Descripción corta para mostrar en /help
            handler: Función asíncrona que ejecuta la lógica del comando
            cooldown_seconds: Tiempo mínimo entre ejecuciones
            requires_auth: Si necesita tenant válido para ejecutarse
        """
        self._commands[name] = SkillCommand(name, description, handler, cooldown_seconds, requires_auth)

    async def execute(
        self,
        name: str,
        params: dict[str, Any],
        tenant_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """
        Ejecutar un comando.

        Verifica que el comando exista, que no esté en cooldown,
        y ejecuta el handler correspondiente.

        Parámetros:
            name: Nombre del comando (con o sin slash)
            params: Parámetros adicionales del comando
            tenant_id: ID del tenant actual
            session_id: ID de la sesión actual

        Retorna:
            Dict con:
                - success: True si el comando se ejecutó
                - command: Nombre del comando ejecutado
                - result: Resultado del handler (o error)
        """
        # Normalizar nombre (quitar slash si existe)
        cmd_name = name.lstrip("/")
        cmd = self._commands.get(cmd_name.lower())

        if not cmd:
            return {
                "success": False,
                "error": f"Comando no encontrado: /{name}. Escribe /help para ver los disponibles.",
            }

        if not cmd.can_execute(tenant_id):
            return {
                "success": False,
                "error": "Comando en cooldown, intenta más tarde",
            }

        cmd.mark_used()

        try:
            result = await cmd.handler(params, tenant_id, session_id)
            return {
                "success": True,
                "command": cmd_name,
                "result": result if isinstance(result, dict) else {"response": str(result)},
            }
        except Exception as e:
            logger.error(f"Error executing command /{cmd_name}: {e}")
            return {
                "success": False,
                "error": f"Error ejecutando comando: {e!s}",
            }

    def list_all(self) -> list:
        """
        Listar todos los comandos disponibles.

        Retorna:
            Lista de dicts con name (con slash) y description
        """
        return [
            {
                "name": f"/{cmd.name}",
                "description": cmd.description,
                "cooldown": cmd.cooldown_seconds,
            }
            for cmd in self._commands.values()
        ]

    # ------------------------------------------------------------------
    # Handler implementations (async)
    # ------------------------------------------------------------------

    async def _cmd_help(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Muestra la ayuda con todos los comandos disponibles.

        Parámetros:
            params: Parámetros adicionales (no usados)
            tenant_id: ID del tenant
            session_id: ID de la sesión

        Retorna:
            Dict con lista de comandos y descripción
        """
        commands = self.list_all()
        response = "Comandos disponibles:\n\n"
        for cmd in commands:
            cooldown_note = ""
            if cmd["cooldown"] > 0:
                cooldown_note = f" (cooldown: {cmd['cooldown']}s)"
            response += f"  /{cmd['name']} - {cmd['description']}{cooldown_note}\n"
        response += "\nUsa cualquier comando escribiendo /<nombre> en tu mensaje."
        return {"response": response}

    async def _cmd_reset(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Resetea la conversación actual.

        Limpia el historial de mensajes y la memoria agotada
        para la sesión específica, manteniendo el perfil del usuario.

        Parámetros:
            params: Parámetros adicionales (no usados)
            tenant_id: ID del tenant
            session_id: ID de la sesión a resetear

        Retorna:
            Dict con mensaje de confirmación
        """
        from ai_platform.orchestrator.session import get_session_manager

        try:
            sm = get_session_manager()
            await sm.reset_session(session_id)
            logger.info(f"Conversation reset: tenant={tenant_id}, session={session_id}")
        except Exception as e:
            logger.error(f"Error resetting session {session_id}: {e}")
            return {"response": "Error al resetear la conversación: " + str(e)}

        return {"response": "Conversación reseteada. El contexto ha sido limpiado."}

    async def _cmd_memory(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Muestra el estado de la memoria.

        Incluye:
        - Memoria del agente (MEMORY.md)
        - Perfil del usuario (USER.md)
        - Capacidad usada por cada una

        Parámetros:
            params: Parámetros adicionales (no usados)
            tenant_id: ID del tenant
            session_id: ID de la sesión

        Retorna:
            Dict con estado de memoria
        """
        from ai_platform.orchestrator.memory import get_memory_manager

        try:
            mgr = get_memory_manager()
            summary = await mgr.get_summary(session_id)
            response = "Estado de memoria:\n\n"
            response += f"  Memoria del agente: {summary['memory']['chars']}/{summary['memory']['max_chars']} chars "
            response += f"({summary['memory']['count']} entradas, {summary['memory']['capacity_percent']}%)\n"
            response += f"  Perfil del usuario: {summary['user']['chars']}/{summary['user']['max_chars']} chars "
            response += f"({summary['user']['count']} entradas, {summary['user']['capacity_percent']}%)\n"
            response += f"  Total usado: {summary['memory']['chars'] + summary['user']['chars']} chars"
            logger.info(f"Memory status requested: session={session_id}")
            return {"response": response}
        except Exception as e:
            logger.error(f"Error getting memory status: {e}")
            return {"response": "Error al obtener estado de memoria: " + str(e)}

    async def _cmd_budget(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Muestra el presupuesto usado.

        Incluye:
        - Costo total gastado
        - Tareas activas
        - Iteraciones totales

        Parámetros:
            params: Parámetros adicionales (no usados)
            tenant_id: ID del tenant
            session_id: ID de la sesión

        Retorna:
            Dict con estadísticas de presupuesto
        """
        from ai_platform.orchestrator.budget import get_budget_tracker

        try:
            tracker = get_budget_tracker()
            stats = await tracker.get_stats(tenant_id)
            response = "Presupuesto usado:\n\n"
            response += f"  Costo total: ${stats['total_cost_usd']:.4f} USD\n"
            response += f"  Tareas completadas: {stats['total_tasks']}\n"
            response += f"  Tareas activas: {stats['active_tasks']}\n"
            response += f"  Iteraciones totales: {stats['total_iterations']}\n"
            logger.info(f"Budget status requested: tenant={tenant_id}")
            return {"response": response}
        except Exception as e:
            logger.error(f"Error getting budget status: {e}")
            return {"response": "Error al obtener estado de presupuesto: " + str(e)}

    async def _cmd_skills(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Muestra las skills disponibles.

        Lista todos los módulos que Odin puede usar:
        ai-connect, ai-content, ai-social, etc.

        Parámetros:
            params: Parámetros adicionales (no usados)
            tenant_id: ID del tenant
            session_id: ID de la sesión

        Retorna:
            Dict con lista de skills
        """
        skills_info = {
            "ai-connect": "Mensajería (WhatsApp, Telegram, Slack, Messenger)",
            "ai-content": "Generación de contenido (textos, posts, blogs)",
            "ai-social": "Gestión de redes sociales (Instagram, Facebook, LinkedIn, TikTok)",
            "ai-leads": "Generación y gestión de leads",
            "ai-ads": "Campañas publicitarias (Meta Ads, Google Ads)",
            "ai-analytics": "Análisis de datos y métricas",
            "ai-web": "Generación de páginas web y landing pages",
        }

        response = "Skills disponibles:\n\n"
        for module, description in skills_info.items():
            response += f"  • {module}: {description}\n"
        response += "\nOdin selecciona automáticamente el skill más apropiado."
        return {"response": response}

    async def _cmd_model(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Cambiar el modelo LLM.

        Acciones:
        - list: Muestra modelos disponibles con sus precios
        - set <model>: Cambia al modelo especificado

        Parámetros:
            params: Dict con action ("list" o "set") y model (si es "set")
            tenant_id: ID del tenant
            session_id: ID de la sesión

        Retorna:
            Dict con lista de modelos o confirmación de cambio
        """
        action = params.get("action", "list")

        if action == "list":
            from ai_platform.orchestrator.llm_client import ROUTING_MODELS
            from ai_platform.orchestrator.pricing import list_available_models

            models = list_available_models()
            response = "Modelos disponibles:\n\n"
            response += "  Modelos de orquestación:\n"
            for role, name in ROUTING_MODELS.items():
                response += f"    - {name} (rol: {role})\n"
            response += "\n  Otros modelos disponibles:\n"

            # Mostrar solo categorías únicas para no saturar
            shown = set()
            for m in models:
                if m["model"] not in shown:
                    shown.add(m["model"])
                    response += f"    - {m['model'][:40]:<40} [{m['category']:>10}] "
                    response += f"${m['input_price_per_1m']:.2f}→${m['output_price_per_1m']:.2f}/1M\n"

            return {"response": response}

        elif action == "set":
            model = params.get("model")
            if not model:
                return {
                    "response": "Uso: /model set <nombre_del_modelo>. Escribe /model list para ver los disponibles."
                }

            from ai_platform.orchestrator.pricing import get_model_pricing, is_model_free

            pricing = get_model_pricing(model)
            free = is_model_free(model)

            return {
                "response": (
                    f"Modelo cambiado a: {model}\n"
                    f"  Categoría: {pricing['category']}\n"
                    f"  Precio: ${pricing['input_price_per_1m']:.2f}→${pricing['output_price_per_1m']:.2f}/1M tokens"
                    f" {'(gratuito)' if free else ''}"
                ),
            }

        return {"response": "Uso: /model list | /model set <nombre_modelo>"}

    async def _cmd_clear(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Limpia el historial de mensajes.

        Diferente de /reset: /clear solo limpia el historial
        de mensajes pero mantiene la memoria del agente.

        Parámetros:
            params: Parámetros adicionales (no usados)
            tenant_id: ID del tenant
            session_id: ID de la sesión

        Retorna:
            Dict con confirmación
        """
        from ai_platform.orchestrator.session import get_session_manager

        try:
            sm = get_session_manager()
            await sm.clear_history(session_id)
            logger.info(f"History cleared: tenant={tenant_id}, session={session_id}")
        except Exception as e:
            logger.error(f"Error clearing history: {e}")
            return {"response": "Error al limpiar el historial: " + str(e)}

        return {"response": "Historial de mensajes limpiado."}

    async def _cmd_summarize(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Genera un resumen de la sesión.

        Usa un LLM para resumir la conversación actual
        en puntos clave.

        Parámetros:
            params: Parámetros adicionales (no usados)
            tenant_id: ID del tenant
            session_id: ID de la sesión

        Retorna:
            Dict con el resumen generado
        """
        from ai_platform.orchestrator.session import get_session_manager

        try:
            sm = get_session_manager()
            messages = await sm.get_messages(session_id, limit=50)
            if not messages:
                return {"response": "No hay mensajes para resumir."}

            # Contar mensajes por rol
            user_count = sum(1 for m in messages if m.get("role") == "user")
            assistant_count = sum(1 for m in messages if m.get("role") == "assistant")

            summary = (
                f"Resumen de la sesión (tenant={tenant_id}):\n\n"
                f"  Mensajes del usuario: {user_count}\n"
                f"  Mensajes del asistente: {assistant_count}\n"
                f"  Total: {len(messages)} mensajes\n"
                f"  Sesión iniciada: {messages[0].get('created_at', 'desconocido') if messages else 'N/A'}\n"
            )
            return {"response": summary}
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return {"response": "Error al generar el resumen: " + str(e)}

    async def _cmd_export(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Exporta la conversación actual en formato JSON.

        Incluye todos los mensajes de la sesión ordenados
        por fecha, útiles para respaldos o migraciones.

        Parámetros:
            params: Parámetros adicionales (no usados)
            tenant_id: ID del tenant
            session_id: ID de la sesión

        Retorna:
            Dict con los mensajes exportados y metadatos
        """
        from ai_platform.orchestrator.session import get_session_manager

        try:
            sm = get_session_manager()
            messages = await sm.get_messages(session_id)

            export_data = {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "exported_at": datetime.now().isoformat(),
                "message_count": len(messages),
                "messages": messages,
            }

            logger.info(f"Conversation exported: session={session_id}, {len(messages)} messages")
            return {
                "response": "Conversación exportada exitosamente.",
                "data": export_data,
            }
        except Exception as e:
            logger.error(f"Error exporting conversation: {e}")
            return {"response": "Error al exportar la conversación: " + str(e)}

    async def _cmd_import(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Importa una conversación guardada.

        Espera un parámetro 'data' con los mensajes importados
        en formato JSON.

        Parámetros:
            params: Dict con la estructura de datos a importar
            tenant_id: ID del tenant
            session_id: ID de la sesión destino

        Retorna:
            Dict con confirmación
        """
        from ai_platform.orchestrator.session import get_session_manager

        try:
            import_data = params.get("data", {})
            messages = import_data.get("messages", [])
            sm = get_session_manager()

            imported_count = 0
            for msg in messages:
                await sm.add_message(
                    session_id=session_id,
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                )
                imported_count += 1

            logger.info(f"Conversation imported: session={session_id}, {imported_count} messages")
            return {"response": f"Conversación importada: {imported_count} mensajes importados."}
        except Exception as e:
            logger.error(f"Error importing conversation: {e}")
            return {"response": "Error al importar la conversación: " + str(e)}

    async def _cmd_status(self, params: dict[str, Any], tenant_id: str, session_id: str) -> dict[str, Any]:
        """
        Muestra el estado actual del sistema.

        Incluye:
        - Estado del servicio LLM
        - Estado de la base de datos
        - Límites de tasa actuales

        Parámetros:
            params: Parámetros adicionales (no usados)
            tenant_id: ID del tenant
            session_id: ID de la sesión

        Retorna:
            Dict con el estado del sistema
        """
        from ai_platform.orchestrator.rate_limiter import get_rate_limit_tracker

        tracker = get_rate_limit_tracker()
        limits = tracker.get_all_limits()

        response = "Estado del sistema:\n\n"
        response += "  LLM (OpenRouter): connected\n"
        response += "  Base de datos: connected\n"
        response += "  Motor de decisiones: activo\n\n"
        response += "  Límites de tasa:\n"
        for service, info in limits.items():
            remaining = info.get("remaining", "N/A")
            response += f"    - {service}: {remaining} requests restantes\n"

        logger.debug(f"System status requested: tenant={tenant_id}")
        return {
            "response": response,
            "limits": limits,
        }


# Instancia global (singleton)
_skill_command_manager: Optional["SkillCommandManager"] = None


def get_skill_command_manager() -> "SkillCommandManager":
    """
    Obtener el gestor de comandos (singleton).

    Patrón singleton: se crea una sola instancia y se reutiliza.

    Retorna:
        Instancia de SkillCommandManager
    """
    global _skill_command_manager
    if _skill_command_manager is None:
        _skill_command_manager = SkillCommandManager()
    return _skill_command_manager
