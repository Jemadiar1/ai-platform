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

import json
import logging
from typing import Any

from ai_platform.core.security import scanner
from ai_platform.orchestrator.budget import BudgetTracker
from ai_platform.orchestrator.knowledge_base import get_knowledge_base
from ai_platform.orchestrator.llm_client import LLMClient
from ai_platform.orchestrator.memory import MemoryManager
from ai_platform.orchestrator.observability import DecisionLogger
from ai_platform.orchestrator.plugins import PluginManager
from ai_platform.orchestrator.session import SessionManager
from ai_platform.orchestrator.skills import SkillManager
from ai_platform.orchestrator.trajectory import Step, TrajectoryManager

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
        self.plugin_manager = PluginManager()
        self.trajectory_manager = TrajectoryManager()
        from ai_platform.orchestrator.subagent import get_subagent_manager

        self.subagent_manager = get_subagent_manager()

    async def decide(
        self,
        prompt: str,
        tenant_id: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
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
                f"Injection patterns detected in prompt from user. "
                f"Patterns: {scan_result['flagged_patterns']}. "
                "Using sanitized version."
            )
            prompt = scanner.sanitize(prompt)

        # Paso 2: Gestionar sesión
        session = await self.session_manager.get_or_create(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
        )
        session_id = session["id"]

        # Paso 2.5: Iniciar tracking de trayectoria
        self.trajectory_manager.start_trajectory(
            session_id=session_id,
            tenant_id=tenant_id,
            user_prompt=prompt,
            tags=["routing"],
        )

        # Paso 3: Cargar contexto de sesión (frozen snapshot)
        session_context = await self.session_manager.get_context(session_id)

        # Paso 4: Escanear memoria relevante
        memory_context = await self.memory_manager.prefetch(
            session_id=session_id,
            prompt=prompt,
        )

        # Paso 4.5: Buscar en base de conocimiento documentos relevantes
        try:
            kb_manager = get_knowledge_base()
            kb_context = await kb_manager.search(
                query=prompt,
                tenant_id=tenant_id,
                limit=3,
            )
        except Exception as e:
            logger.warning(f"Error en búsqueda de base de conocimiento: {e}")
            kb_context = []

        # Paso 5: Construir historial relevante
        history = session_context.get("recent_messages", [])

        # Paso 5.5: Ejecutar hooks de plugins antes de decidir
        try:
            await self.plugin_manager.execute_hook(
                "on_decide",
                session_id=session_id,
                tenant_id=tenant_id,
                prompt=prompt,
            )
        except Exception as e:
            logger.warning(f"Plugin on_decide hook failed: {e}")

        # Paso 6: Consultar LLM para routing
        try:
            routing = await self.llm_client.route_task(
                prompt=prompt,
                tenant_id=tenant_id,
                history=history,
            )
        except RuntimeError as e:
            logger.warning(f"LLM unavailable, using fallback: {e}")
            routing = await self.llm_client._route_with_fallback(prompt, tenant_id, history)

        # Paso 6.5: Registrar paso de routing en trayectoria
        self.trajectory_manager.add_step(
            session_id,
            Step(
                step_type="route",
                module=routing.get("module"),
                params={"prompt_preview": prompt[:100]},
                result=routing.get("reasoning", ""),
                latency_ms=routing.get("latency_ms"),
            ),
        )

        # Paso 7: Registrar decisión en observabilidad
        self.decision_logger.log_decision(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "session_id": session_id,
                "prompt": prompt[:100],  # Truncar para evitar logs enormes
                "module": routing["module"],
                "action": routing["action"],
                "confidence": routing["confidence"],
                "reasoning": routing["reasoning"],
            }
        )

        # Paso 8: Si necesita descomposición, descomponer
        subtasks = []
        if routing.get("needs_decomposition"):
            subtasks = await self.llm_client.decompose_task(
                prompt=prompt,
                tenant_id=tenant_id,
            )
            self.trajectory_manager.add_step(
                session_id,
                Step(
                    step_type="decompose",
                    params={"subtask_count": len(subtasks)},
                    result=json.dumps(subtasks, default=str)[:500],
                ),
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
            "kb_context": kb_context,
        }

    async def execute(
        self,
        decision: dict[str, Any],
        tenant_id: str,
        task_id: str,
    ) -> dict[str, Any]:
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
        params = decision["params"]
        session_id = decision.get("session_id")

        # Validar que el módulo sea soportado
        supported_modules = {"ai-connect", "ai-social", "ai-web", "ai-content", "ai-marketing", "ai-sales"}
        if module not in supported_modules and module != "uncategorized":
            self.trajectory_manager.add_step(
                session_id,
                Step(
                    step_type="error",
                    module=module,
                    error=f"Unsupported module: {module}",
                ),
            )
            return {
                "status": "error",
                "error": f"El módulo '{module}' no es soportado",
            }

        if module == "uncategorized":
            self.trajectory_manager.add_step(
                session_id,
                Step(
                    step_type="error",
                    module="uncategorized",
                    error="No module matched the user prompt.",
                ),
            )
            self.trajectory_manager.complete_trajectory(session_id)
            return {
                "module": "uncategorized",
                "status": "failed",
                "result": {
                    "error": "No module matched the user prompt.",
                    "message": "Please rephrase your request.",
                },
            }

        # Ejecutar hooks de plugins antes de ejecutar
        try:
            await self.plugin_manager.execute_hook(
                "on_execute",
                session_id=session_id,
                tenant_id=tenant_id,
                module=module,
                action=decision.get("action"),
            )
        except Exception as e:
            logger.warning(f"Plugin on_execute hook failed: {e}")

        # Inyectar contexto en la payload
        enriched_payload = self._enrich_payload(params, decision)

        # Tracking de budget
        await self.budget_tracker.begin_task(task_id, tenant_id, module)

        try:
            # Simular ejecución del módulo
            # En producción, esto invocará al handler del módulo
            result = await self._invoke_module(module, enriched_payload)

            # Registrar paso de ejecución en trayectoria
            self.trajectory_manager.add_step(
                session_id,
                Step(
                    step_type="execute",
                    module=module,
                    params={"task_id": task_id},
                    result=json.dumps(result, default=str)[:500],
                ),
            )

            # Ejecutar subagentes si la decisión los requiere
            if decision.get("needs_decomposition") and decision.get("subtasks"):
                subagent_results = await self.subagent_manager.execute_subagents(
                    parent_session_id=decision.get("session_id"),
                    tenant_id=tenant_id,
                    subtasks=decision["subtasks"],
                )
                main_result = result.get("result", {})
                for sub_result in subagent_results:
                    main_result[f"subagent_{sub_result.module}"] = sub_result.result
                result["result"] = main_result

            await self.budget_tracker.end_task(task_id, module, success=True)

            # Actualizar memoria con esta interacción
            await self.memory_manager.sync_turn(
                session_id=decision.get("session_id"),
                user_message="",  # Ya tenemos el prompt original
                assistant_result=result,
            )

            # Completar trayectoria
            self.trajectory_manager.complete_trajectory(session_id)

            return {
                "module": module,
                "status": "completed",
                "result": result,
            }

        except Exception as e:
            await self.budget_tracker.end_task(task_id, module, success=False, error=str(e))
            # Registrar error en trayectoria
            self.trajectory_manager.add_step(
                session_id,
                Step(
                    step_type="error",
                    module=module,
                    error=str(e),
                ),
            )
            self.trajectory_manager.complete_trajectory(session_id)
            raise

    async def close(self) -> None:
        """Cerrar todos los recursos."""
        await self.plugin_manager.stop()
        await self.llm_client.close()
        await self.session_manager.close()
        await self.memory_manager.close()
        await self.skill_manager.close()
        await self.budget_tracker.close()

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _enrich_payload(self, params: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        """
        Enriquecer la payload con contexto de sesión y memoria.

        Esto aplica el principio de memoria congelada de Hermes:
        inyectar el contexto una vez al inicio y mantenerlo estable
        durante la sesión.
        """
        enriched = {**params}
        enriched["tenant_id"] = decision.get("session_context", {}).get("tenant_id")

        # Inyectar contextos si disponibles
        if "session_context" in decision:
            enriched["session_context"] = decision["session_context"]

        if "memory_context" in decision:
            enriched["memory_context"] = decision["memory_context"]

        if "kb_context" in decision:
            enriched["kb_context"] = decision["kb_context"]

        return enriched

    async def _invoke_module(
        self,
        module: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Invocar al handler del módulo seleccionado.

        En esta fase inicial, retorna un placeholder.
        En producción, importará dinámicamente el handler del módulo.
        """
        # TODO: Importación dinámica del handler
        # from ai_platform.modules.ai_connect.handler import execute
        # result = await execute(payload)

        return {
            "module": module,
            "status": "completed",
            "message": f"Module {module} executed successfully.",
            "payload": payload,
        }


# Instancia global
_ragnar: Ragnar | None = None


def get_ragnar() -> Ragnar:
    """
    Obtener la instancia de Ragnar.
    Patrón singleton: se crea UNA SOLA VEZ y se reutiliza.
    """
    global _ragnar
    if _ragnar is None:
        _ragnar = Ragnar()
    return _ragnar
