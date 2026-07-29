"""
Motor de decisión principal de Odin.

Odin recibe un input del usuario y decide:
1. Qué módulo ejecutar (LLM-based + rule-based fallback)
2. Qué parámetros extraer del input
3. Si necesita descomposición en múltiples módulos
4. Qué contexto de sesión proporcionar

Integración con SOUL.md:
- Siempre propaga tenant_id en cada tarea
- Prioriza el aislamiento entre módulos
- Registra observabilidad en decisiones críticas

Uso:
    Odin = Odin()
    decision = await Odin.decide(prompt, tenant_id, history)
    # decision = {module, action, params, confidence, ...}
"""

import asyncio
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


class Odin:
    """
    El orquestador principal de AI Platform.

    Odin es el cerebro que decide qué módulo especializado
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

        Este es el método central de Odin. Flujos:
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
            raise ValueError("tenant_id es obligatorio para toda decisión de Odin")

        # Paso 1: Sanitizar input contra inyección de prompts
        scan_result = scanner.scan(prompt)
        if not scan_result["is_safe"]:
            logger.warning(
                f"Injection patterns detected in prompt from user. "
                f"Patterns: {scan_result['flagged_patterns']}. "
                "Using sanitized version."
            )
            prompt = scanner.sanitize(prompt)

        # Paso 1.5: Fast-path pre-routing para saludos y consultas conversacionales (0.001s latency)
        clean_p = prompt.strip().lower().rstrip("!?.")
        conversational_keywords = [
            "hola", "buenos dias", "buenos días", "buenas tardes", "buenas noches",
            "hey", "saludos", "quien eres", "quién eres", "que haces", "qué haces",
            "que puedes hacer", "qué puedes hacer", "capacidades", "servicios",
            "información", "informacion", "neuralcrew", "ayuda", "help", "inicio",
            "start", "gracias", "contacto", "que ofrecen", "qué ofrecen"
        ]
        if any(k in clean_p for k in conversational_keywords):
            session = await self.session_manager.get_or_create(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            real_session_id = session["id"]
            logger.info(f"Odin fast-path match: consulta conversacional -> ai-connect")
            return {
                "module": "ai-connect",
                "action": "send_message",
                "confidence": 1.0,
                "reasoning": "Fast-path rule match: consulta conversacional",
                "needs_decomposition": False,
                "prompt": prompt,
                "message_text": prompt,
                "params": {"message_text": prompt},
                "session_id": real_session_id,
                "session_context": {},
                "memory_context": "",
                "kb_context": [],
            }

        # Fast-path rule para reinicio de sesión / limpiar contexto
        reset_keywords = ["/reset", "/clear", "/limpiar", "reiniciar sesion", "reiniciar sesión", "borrar contexto", "nueva sesion", "nueva sesión"]
        if any(k in clean_p for k in reset_keywords):
            if session_id:
                try:
                    await self.session_manager.end(session_id, tenant_id)
                except Exception:
                    pass
            new_session = await self.session_manager.create(
                tenant_id=tenant_id,
                user_id=user_id,
                title=f"Sesión nueva de {user_id or 'usuario'}",
            )
            reset_msg = (
                "🔄 <b>Sesión e historial reiniciados con éxito.</b>\n\n"
                "Se ha eliminado el contexto acumulado de la conversación. "
                "Puedes iniciar una nueva solicitud desde cero (ej: redactar un nuevo guion o informe)."
            )
            logger.info(f"Odin fast-path match: reinicio de sesión -> new_session_id={new_session.id}")
            return {
                "module": "ai-connect",
                "action": "send_message",
                "confidence": 1.0,
                "reasoning": "Fast-path rule match: reinicio de sesión",
                "needs_decomposition": False,
                "prompt": prompt,
                "message_text": reset_msg,
                "params": {"message_text": reset_msg},
                "session_id": new_session.id,
                "session_context": {},
                "memory_context": "",
                "kb_context": [],
            }

        # Fast-path rule para creación/renderizado de archivos de documentos (.docx, .xlsx, .pptx, .pdf)
        doc_exts = [".docx", ".xlsx", ".pptx", ".pdf", "docx", "xlsx", "pptx"]
        action_verbs = ["crea", "crear", "genera", "generar", "redacta", "redactar", "haz", "hacer", "escribe", "escribir", "exporta", "exportar", "descargar", "dame", "hazme", "en word", "en excel", "en pdf"]
        
        is_query_about_skills = any(q in clean_p for q in ["hablarme", "habilidades", "puedes hacer", "qué haces", "cómo funciona", "explicar", "cuáles son", "sabes hacer"])
        is_explicit_doc_request = any(e in clean_p for e in doc_exts) or (any(v in clean_p for v in action_verbs) and any(k in clean_p for k in ["documento", "guion", "guión", "word", "excel", "pdf", "script", "plantilla"]))

        if is_explicit_doc_request and not is_query_about_skills:
            session = await self.session_manager.get_or_create(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            real_session_id = session["id"]
            fmt = "docx"
            if any(x in clean_p for x in ["excel", "xlsx", "hoja de calculo", "tabla"]):
                fmt = "xlsx"
            elif any(x in clean_p for x in ["pptx", "powerpoint", "presentacion", "diapositiva"]):
                fmt = "pptx"
            elif "pdf" in clean_p:
                fmt = "pdf"

            # Recompilar historial reciente de la sesión para no perder el contexto previo (guión, tono, marca)
            session_ctx = await self.session_manager.get_context(real_session_id)
            recent = session_ctx.get("recent_messages", [])
            history_lines = [f"{msg.get('role', 'user').upper()}: {msg.get('content', '')}" for msg in recent if msg.get("content")]
            full_context = "\n\n".join(history_lines) if history_lines else prompt

            logger.info(f"Odin fast-path match: solicitud de documento ({fmt}) -> ai-documents con historial de {len(recent)} msgs")
            return {
                "module": "ai-documents",
                "action": "generate_document",
                "confidence": 1.0,
                "reasoning": f"Fast-path rule match: creación de documento {fmt}",
                "needs_decomposition": False,
                "prompt": prompt,
                "message_text": prompt,
                "params": {"format": fmt, "subject": prompt, "content": full_context, "title": prompt},
                "session_id": real_session_id,
                "session_context": {},
                "memory_context": "",
                "kb_context": [],
            }

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
            tenant_id=tenant_id,
            user_id=user_id,
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
                memory_context=memory_context,
            )
        except Exception as e:
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
            substeps_start = self.trajectory_manager.get_active_trajectory(session_id)
            subtasks = await self.llm_client.decompose_task(
                complex_prompt=prompt,
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
            "prompt": prompt,
            "message_text": prompt,
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
        Ejecutar una tarea basada en la decisión de Odin.

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
        logger.info(f"ODIN execute: module={module!r}, action={decision.get('action')}")
        session_id = decision.get("session_id") or decision.get("session_context", {}).get("id")

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

        # Validar módulo soportado
        supported_modules = {
            "ai-connect",
            "ai-content",
            "ai-social",
            "ai-leads",
            "ai-ads",
            "ai-analytics",
            "ai-web",
            "ai-documents",
        }
        if module not in supported_modules:
            self.trajectory_manager.add_step(
                session_id,
                Step(
                    step_type="error",
                    module=module,
                    error=f"Module {module} no soportado",
                ),
            )
            self.trajectory_manager.complete_trajectory(session_id)
            return {
                "module": module,
                "status": "error",
                "error": f"Módulo {module} no soportado",
            }

        # Tracking de budget
        self.budget_tracker.begin_task(task_id, tenant_id, module)

        # Verificar licencia del tenant para este agente
        from ai_platform.middleware.licensing import check_agent_access

        # Obtener plan del tenant desde la BD
        from uuid import UUID
        from sqlalchemy import select
        from ai_platform.database import session_factory
        from ai_platform.models.db import Tenant

        tenant_session = session_factory()
        try:
            tenant_plan = "enterprise"
            t_uuid = UUID(str(tenant_id)) if isinstance(tenant_id, str) else tenant_id
            tenant_record = tenant_session.execute(select(Tenant).where(Tenant.id == t_uuid)).scalar_one_or_none()
            if tenant_record and tenant_record.plan:
                tenant_plan = str(tenant_record.plan).lower()
        except Exception as e:
            logger.warning(f"Error resolviendo plan de tenant {tenant_id}: {e}. Asumiendo 'enterprise'.")
            tenant_plan = "enterprise"
        finally:
            tenant_session.close()

        access = check_agent_access(tenant_id=tenant_id, agent_name=module, plan=tenant_plan)
        if not access["allowed"]:
            self.trajectory_manager.add_step(
                session_id,
                Step(
                    step_type="error",
                    module=module,
                    error="Access denied: agent not licensed",
                ),
            )
            self.trajectory_manager.complete_trajectory(session_id)
            return {
                "module": module,
                "status": "error",
                "error": "Acceso denegado",
                "reason": access["reason"],
            }

        # Inyectar contexto en la payload
        enriched_payload = self._enrich_payload(params, decision)

        # Pre-execution fallback: document_ingest sin params → redirigir a ai-connect
        if module == "ai-analytics" and decision.get("action") == "document_ingest":
            has_file = enriched_payload.get("file_bytes") or enriched_payload.get("file_base64") or enriched_payload.get("original_filename")
            if not has_file:
                logger.warning(f"document_ingest sin archivo, redirigiendo a ai-connect:send_message")
                module = "ai-connect"
                decision["module"] = "ai-connect"
                decision["action"] = "send_message"
                decision["params"] = {}
                enriched_payload = self._enrich_payload({}, decision)

        try:
            # Simular ejecución del módulo
            # En producción, esto invocará al handler del módulo
            result = await self._invoke_module(module, enriched_payload)

            # Fallback: si la acción no es válida, reintentar con "default"
            if (
                isinstance(result, dict)
                and result.get("status") == "failed"
                and "no encontrada" in result.get("error", "")
            ):
                logger.warning(f"Action inválida en {module}, reintentando con 'default': {result.get('error')}")
                enriched_payload["action"] = "default"
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

            self.budget_tracker.end_task(task_id, module, success=True)

            # Actualizar memoria con esta interacción
            await self.memory_manager.sync_turn(
                session_id=decision.get("session_id"),
                user_message="",  # Ya tenemos el prompt original
                assistant_result=result,
            )

            # Completar trayectoria
            self.trajectory_manager.complete_trajectory(session_id)

            # Consolidar memoria de la sesión en el perfil cross-session del usuario
            try:
                user_id = decision.get("user_id") or decision.get("session_context", {}).get("user_id", "")
                await self.memory_manager.consolidate_session(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    user_id=user_id or "",
                )
            except Exception as e:
                logger.warning(f"Memory consolidation failed: {e}")

            return {
                "module": module,
                "status": "completed",
                "result": result,
            }

        except Exception as e:
            self.budget_tracker.end_task(task_id, module, success=False, error=str(e))
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
        enriched["module"] = decision["module"]
        enriched["action"] = decision.get("action", "send_message")
        enriched["tenant_id"] = decision.get("session_context", {}).get("tenant_id")

        prompt = decision.get("prompt") or decision.get("message_text") or params.get("prompt") or params.get("message_text", "")
        if prompt:
            enriched["prompt"] = prompt
            enriched["message_text"] = prompt
            if "params" in enriched and isinstance(enriched["params"], dict):
                enriched["params"]["message_text"] = prompt
                enriched["params"]["prompt"] = prompt

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

        Importa dinámicamente la clase Handler del módulo y ejecuta
        execute(payload). Sigue el mismo patrón usado por webhooks,
        channels y task_runner para consistencia.

        Parámetros:
            module: Nombre del módulo (ej: "ai-connect")
            payload: Payload enriquecido con contexto

        Retorna:
            Dict con resultado del handler
        """
        from ai_platform.orchestrator.modules import get_handler

        HandlerClass = get_handler(module)
        if HandlerClass is None:
            return {
                "module": module,
                "status": "error",
                "error": f"Handler no encontrado para módulo: {module}",
            }

        try:
            handler_instance = HandlerClass()
            if asyncio.iscoroutinefunction(handler_instance.execute):
                result = await handler_instance.execute(payload)
            else:
                res = handler_instance.execute(payload)
                if asyncio.iscoroutine(res):
                    result = await res
                else:
                    result = res
            return result if isinstance(result, dict) else {"status": "ok", "data": result}
        except Exception as e:
            logger.error(f"Module execution failed: {module} -> {e}")
            raise


# Instancia global
_odin: Odin | None = None


def get_odin() -> Odin:
    """
    Obtener la instancia de Odin.
    Patrón singleton: se crea UNA SOLA VEZ y se reutiliza.
    """
    global _odin
    if _odin is None:
        _odin = Odin()
    return _odin
