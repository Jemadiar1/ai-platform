"""
Motor de decisión principal de Ragnar.

Ragnar recibe un input del usuario y decide:
1. Qué módulo ejecutar (LLM-based + rule-based fallback)
2. Qué parámetros extraer del input
3. Si necesita descomposición en múltiples módulos
4. Qué contexto de sesión proporcionar

Integración con SOUL.md:
- Siempre propaga tenant_id en cada tarea
- Prioriza el aislamiento entre módulos
- Registra observabilidad en decisiones críticas

Uso:
    ragnar = Ragnar()
    decision = await ragnar.decide(prompt, tenant_id, history)
    # decision = {module, action, params, confidence, ...}
"""

import asyncio
import importlib
import json
import logging
from typing import Optional, Dict, Any, List

from ai_platform.orchestrator.llm_client import LLMClient
from ai_platform.orchestrator.session import SessionManager
from ai_platform.orchestrator.memory import MemoryManager
from ai_platform.orchestrator.skills import SkillManager
from ai_platform.orchestrator.budget import BudgetTracker
from ai_platform.orchestrator.observability import DecisionLogger
from ai_platform.core.security import scanner, prompt_sanitizer
from ai_platform.modules import MODULE_HANDLERS, VALID_MODULES

logger = logging.getLogger(__name__)


class Ragnar:
    """
    El orquestador principal de AI Platform.

    Ragnar es el cerebro que decide qué módulo especializado
    debe actuar en cada tarea. Mantiene el contexto de sesión,
    la memoria y coordina la ejecución entre los 7 módulos.

    Principios (de SOUL.md):
    1. Decide qué módulo ejecutar basado en el intent del usuario
    2. Siempre propaga tenant_id en cada decisión
    3. Prioriza el aislamiento entre módulos (no mezclar contextos)
    4. Registra observabilidad en cada decisión crítica
    5. Coordina módulos sin mezclar contexto entre clientes
    """

    def __init__(self):
        self.llm_client = LLMClient()
        self.session_manager = SessionManager()
        self.memory_manager = MemoryManager()
        self.skill_manager = SkillManager()
        self.budget_tracker = BudgetTracker()
        self.decision_logger = DecisionLogger()

    async def decide(
        self,
        prompt: str,
        tenant_id: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Decidir qué módulo debe ejecutar una tarea.

        Este es el método central de Ragnar. Flujos:
        1. Sanitizar input contra inyección
        2. Cargar contexto de sesión
        3. Escanear memoria relevante
        4. Consultar LLM para routing
        5. Si neces descomposición → descomponer
        6. Extraer parámetros
        7. Registrar observabilidad
        8. Retornar decisión

        Parámetros:
            prompt: Input del usuario
            tenant_id: ID del tenant actual (obligatorio)
            user_id: ID del usuario (opcional)
            session_id: ID de sesión existente (opcional)

        Retorna:
            Dict con decisión de routing:
                - module: str
                - action: str
                - params: dict
                - confidence: float
                - reasoning: str
                - needs_decomposition: bool
                - subtasks: list (si needs_decomposition=True)
                - session_id: str (nueva o existente)
        """
        # Paso 0: Validar tenant_id (principio de SOUL.md)
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio para toda decisión de Ragnar")

        # Paso 1: Sanitizar input contra inyección de prompts
        scan_result = scanner.scan(prompt)
        if not scan_result["is_safe"]:
            logger.warning(
                f"Se detectaron patrones de inyección en el prompt de un usuario. "
                f"Patrones: {scan_result['flagged_patterns']}. "
                "Usando versión sanitizada."
            )
            prompt = scanner.sanitize(prompt)

        # Paso 2: Gestionar sesión
        session = await self.session_manager.get_or_create(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
        )
        session_id = session["id"]

        # Paso 3: Cargar contexto de sesión (frozen snapshot)
        session_context = await self.session_manager.get_context(session_id)

        # Paso 4: Escanear memoria relevante
        memory_context = await self.memory_manager.prefetch(
            session_id=session_id,
            prompt=prompt,
        )

        # Paso 5: Construir historial relevante
        history = session_context.get("recent_messages", [])

        # Paso 6: Consultar LLM para routing
        try:
            routing = await self.llm_client.route_task(
                prompt=prompt,
                tenant_id=tenant_id,
                history=history,
            )
        except RuntimeError as e:
            logger.warning(f"LLM unavailable, using fallback: {e}")
            routing = await self.llm_client._route_with_fallback(
                prompt, tenant_id, history
            )

        # Paso 7: Registrar decisión en observabilidad
        self.decision_logger.log_decision({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_id,
            "prompt": prompt[:100],  # Truncar para evitar logs enormes
            "module": routing["module"],
            "action": routing["action"],
            "confidence": routing["confidence"],
            "reasoning": routing["reasoning"],
        })

        # Paso 8: Si necesita descomposición, descomponer
        subtasks = []
        if routing.get("needs_decomposition"):
            subtasks = await self.llm_client.decompose_task(
                prompt=prompt,
                tenant_id=tenant_id,
            )

        # Paso 9: Extraer parámetros específicos del módulo
        params = await self.llm_client.extract_params(
            prompt=prompt,
            module=routing["module"],
            action=routing["action"],
        )

        return {
            **routing,
            "params": params,
            "subtasks": subtasks,
            "session_id": session_id,
            "session_context": session_context,
            "memory_context": memory_context,
        }

    async def execute(
        self,
        decision: Dict[str, Any],
        tenant_id: str,
        task_id: str,
    ) -> Dict[str, Any]:
        """
        Ejecutar una tarea basada en la decisión de Ragnar.

        Este método coordina la ejecución del módulo seleccionado:
        1. Inyectar contexto de sesión y memoria en la payload
        2. Calcular budget para la tarea
        3. Ejecutar el módulo (esto será llamado por el worker)
        4. Guardar resultado y actualizar memoria
        5. Devolver resultado

        Parámetros:
            decision: Resultado de decide()
            tenant_id: ID del tenant
            task_id: ID de la tarea en BD

        Retorna:
            Dict con resultado de la ejecución
        """
        module = decision["module"]

        if module == "uncategorized":
            return {
                "module": "uncategorized",
                "status": "failed",
                "result": {
                    "error": "Ningún módulo coincidió con el prompt del usuario.",
                    "message": "Por favor, reformule su solicitud.",
                },
            }

        # Inyectar contexto en la payload
        enriched_payload = self._enrich_payload(decision)

        # Tracking de budget
        await self.budget_tracker.begin_task(task_id, tenant_id, module)

        try:
            # Invocar el handler del módulo seleccionado
            # Las excepciones se propagan al except para corregir
            # el estado de budget y retornar un error estructurado.
            result = await self._invoke_module(module, enriched_payload)

            await self.budget_tracker.end_task(task_id, module, success=True)

            # Actualizar memoria con esta interacción
            await self.memory_manager.sync_turn(
                session_id=decision.get("session_id"),
                user_message="",  # Ya tenemos el prompt original
                assistant_result=result,
            )

            return {
                "module": module,
                "status": "completed",
                "result": result,
            }

        except Exception as e:
            # Cuando _invoke_module lanza, el budget se marca como fallo
            # y se retorna un error estructurado (no double-wrapped).
            await self.budget_tracker.end_task(task_id, module, success=False, error=str(e))
            return {
                "module": module,
                "status": "failed",
                "result": {"error": str(e)},
            }

    async def close(self) -> None:
        """Cerrar todos los recursos."""
        await self.llm_client.close()
        await self.session_manager.close()
        await self.memory_manager.close()
        await self.skill_manager.close()
        await self.budget_tracker.close()

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _enrich_payload(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enriquecer la payload con contexto de sesión y memoria.

        Esto aplica el principio de memoria congelada de Hermes:
        inyectar el contexto una vez al inicio y mantenerlo estable
        durante la sesión.

        Valida que tenant_id esté presente. Si no lo está, lanza
        ValueError para evitar propagar None silenciosamente.

        Parámetros:
            decision: Dict retornado por decide()

        Retorna:
            Dict enriquecido con tenant_id, session_context y/or memory_context.

        Raises:
            ValueError: Si no se puede obtener tenant_id de la decisión.
        """
        # Extraer tenant_id del contexto de sesión con validación estricta
        tenant_id = decision.get("session_context", {}).get("tenant_id")
        if not tenant_id:
            raise ValueError(
                "tenant_id must be propagated through enriched payload"
            )

        enriched = {"tenant_id": tenant_id}

        # Inyectar contextos si disponibles
        if "session_context" in decision:
            enriched["session_context"] = decision["session_context"]

        if "memory_context" in decision:
            enriched["memory_context"] = decision["memory_context"]

        return enriched

    async def _invoke_module(
        self,
        module: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Invocar al handler del módulo seleccionado.

        Mapea nombres de módulo (ej: "ai-connect") al handler correspondiente
        usando el registro centralizado (MODULE_HANDLERS). Importa la clase
        Handler, instancia y ejecuta Handler().execute(payload) de forma
        asíncrona vía to_thread.

        Las excepciones se propagan al caller (execute) para que se pueda
        corregir el estado del budget_tracker y retornar un error estructurado.

        Parámetros:
            module: Nombre del módulo a invocar (ej: "ai-connect").
            payload: Payload enriquecido con contexto.

        Retorna:
            Dict con el resultado del handler.

        Raises:
            ImportError: Si el módulo no se puede importar.
            AttributeError: Si no hay clase Handler en el módulo.
            Exception: Cualquier otro error durante la ejecución.
        """
        handler_path = MODULE_HANDLERS.get(module)
        if not handler_path:
            logger.warning("Módulo no registrado: %s", module)
            raise ValueError(
                f"Módulo no soportado: {module}. Módulos válidos: {VALID_MODULES}"
            )

        # Importar el módulo del handler dinámicamente
        handler_module = importlib.import_module(handler_path)
        handler_class = getattr(handler_module, "Handler", None)
        if handler_class is None:
            raise AttributeError(
                f"No se encontró la clase Handler en {handler_path}"
            )

        handler_instance = handler_class()

        # El execute es síncrono, ejecutar en thread para no bloquear el event loop
        result = await asyncio.to_thread(handler_instance.execute, payload)

        logger.info("módulo_ejecutado", module=module)
        return result


# Instancia global
_ragnar: Optional[Ragnar] = None


def get_ragnar() -> Ragnar:
    """
    Obtener la instancia de Ragnar.
    Patrón singleton: se crea UNA SOLA VEZ y se reutiliza.
    """
    global _ragnar
    if _ragnar is None:
        _ragnar = Ragnar()
    return _ragnar
