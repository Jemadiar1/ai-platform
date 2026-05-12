"""
Sistema de subagentes para Ragnar.

Inspirado en Hermes Agent: el agente principal puede crear subagentes
especializados para tareas específicas, ejecutándolos en paralelo
y coordinando los resultados.

Patrones de Hermes aplicados:
- Subagentes como instancias livianas del orquestador
- Contexto aislado por subagente
- Timeout por subagente (TERMINAL_TIMEOUT style)
- Límite de subagentes paralelos (evita sobrecargar LLM API)
- Resultados coordinados en el agente padre
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class SubagentResult:
    """Resultado de un subagente ejecutado."""

    agent_id: str
    module: str
    status: str  # "completed", "timeout", "failed"
    result: Dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertir a dict serializable."""
        return {
            "agent_id": self.agent_id,
            "module": self.module,
            "status": self.status,
            "result": self.result,
            "cost_usd": self.cost_usd,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class Subtask:
    """Subtarea para ejecutar en un subagente."""

    module: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: Optional[str] = None  # Índice de la subtarea dependiente


class SubagentManager:
    """
    Gestiona la creación y ejecución de subagentes.

    Patrón de Hermes Agent: subagentes son instancias livianas
    del orquestador con contexto acotado y timeout.

    Limitaciones (como Hermes):
    - Máx 3 subagentes en paralelo (evita sobrecargar LLM API)
    - Timeout de 120s por subagente (TERMINAL_TIMEOUT style)
    - Contexto aislado por subagente
    """

    def __init__(self):
        self.max_parallel_subagents = 3  # Límite como Hermes
        self.subagent_timeout = 120  # 2 minutos como máximo

    async def execute_subagents(
        self,
        parent_session_id: str,
        tenant_id: str,
        subtasks: List[Dict[str, Any]],
    ) -> List[SubagentResult]:
        """
        Ejecutar múltiples subagentes en paralelo.

        Los subagentes se ejecutan concurrentemente con un límite
        de paralelismo para evitar sobrecargar la API del LLM.

        Parámetros:
            parent_session_id: ID de la sesión padre
            tenant_id: ID del tenant
            subtasks: Lista de subtareas a ejecutar

        Retorna:
            Lista de SubagentResult con los resultados
        """
        if not subtasks:
            return []

        # Limitar ejecución paralela (como Hermes)
        semaphore = asyncio.Semaphore(self.max_parallel_subagents)

        async def _run_with_sem(task: Dict[str, Any]) -> SubagentResult:
            async with semaphore:
                return await self._execute_single_subagent(task)

        tasks = [_run_with_sem(task) for task in subtasks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filtrar excepciones y retornar solo resultados válidos
        return [
            r
            for r in results
            if isinstance(r, SubagentResult)
        ]

    async def _execute_single_subagent(
        self,
        subtask: Dict[str, Any],
    ) -> SubagentResult:
        """
        Ejecutar un único subagente con timeout.

        Importa dinámicamente el handler del módulo y lo ejecuta
        con un timeout para evitar bloqueos.

        Parámetros:
            subtask: Dict con keys "module", "action", "params"

        Retorna:
            SubagentResult con el resultado o error
        """
        module = subtask["module"]
        action = subtask["action"]
        params = subtask.get("params", {})

        # Crear contexto aislado para el subagente
        params = {**params, "subtask": True}

        try:
            # Importar handler dinámicamente
            handler_path = f"ai_platform.modules.{module}.handler"
            import importlib

            handler_module = importlib.import_module(handler_path)
            handler = handler_module.Handler()

            # Ejecutar con timeout (como Hermes TERMINAL_TIMEOUT)
            result = await asyncio.wait_for(
                self._call_handler(handler, params),
                timeout=self.subagent_timeout,
            )

            # Calcular costo si pricing info está disponible
            cost = 0.0
            try:
                from ai_platform.orchestrator.pricing import calculate_cost

                cost = calculate_cost(0, 0, module)  # Placeholder
            except Exception:
                pass

            return SubagentResult(
                agent_id=f"subagent_{datetime.now(timezone.utc).timestamp()}",
                module=module,
                status="completed",
                result=result if isinstance(result, dict) else {"response": str(result)},
                cost_usd=cost,
                completed_at=datetime.now(timezone.utc),
            )

        except asyncio.TimeoutError:
            logger.warning(f"Subagent timeout for {module}:{action}")
            return SubagentResult(
                agent_id=f"subagent_timeout_{datetime.now(timezone.utc).timestamp()}",
                module=module,
                status="timeout",
                result={"error": "timeout_exceeded"},
                completed_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(f"Subagent error for {module}:{action}: {e}")
            return SubagentResult(
                agent_id=f"subagent_error_{datetime.now(timezone.utc).timestamp()}",
                module=module,
                status="failed",
                result={"error": str(e)},
                completed_at=datetime.now(timezone.utc),
            )

    async def _call_handler(self, handler: Any, params: Dict) -> Any:
        """
        Invocar el handler del módulo correctamente.

        Detecta si el método execute es async y lo awaitea
        o lo ejecuta en un thread si es sync.

        Parámetros:
            handler: Instancia del Handler del módulo
            params: Parámetros de ejecución

        Retorna:
            Resultado de la ejecución
        """
        if asyncio.iscoroutinefunction(handler.execute):
            return await handler.execute(params)
        else:
            return await asyncio.to_thread(handler.execute, params)


# Instancia global
_subagent_manager: Optional[SubagentManager] = None


def get_subagent_manager() -> SubagentManager:
    """
    Obtener gestor de subagentes (singleton).

    Retorna:
        Instancia de SubagentManager
    """
    global _subagent_manager
    if _subagent_manager is None:
        _subagent_manager = SubagentManager()
    return _subagent_manager
