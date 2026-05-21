"""
Tracker de budget para Odin.

Controla el uso de tokens y costos por tarea y tenant.

Patrones de Hermes:
- Iteration budget: presupuesto compartido entre parent y subagents
- Token counting: tracking de tokens por turno
- Cost tracking: costo en USD por tarea
- Budget enforcement: limitar tareas cuando se alcanza el límite

Uso:
    tracker = BudgetTracker()
    await tracker.begin_task(task_id, tenant_id, module)
    # ... ejecutar tarea ...
    await tracker.end_task(task_id, module, success=True)
    stats = await tracker.get_stats(tenant_id)
"""

import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Límites por defecto
DEFAULT_MAX_ITERATIONS = 50
DEFAULT_MAX_COST_USD = 100.0


class TaskBudget:
    """
    Presupuesto para una tarea individual.
    """

    def __init__(self, task_id: str, tenant_id: str, module: str):
        self.task_id = task_id
        self.tenant_id = tenant_id
        self.module = module
        self.iterations = 0
        self.tokens_input = 0
        self.tokens_output = 0
        self.cost_usd = 0.0
        self.started_at = time.time()
        self.completed_at: float | None = None
        self.success = False
        self.error: str | None = None

    def record_turn(
        self,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """
        Registrar un turno (llamada a LLM).

        Parámetros:
            input_tokens: Tokens de entrada
            output_tokens: Tokens de salida
            cost_usd: Costo en USD de esta llamada
        """
        self.iterations += 1
        self.tokens_input += input_tokens
        self.tokens_output += output_tokens
        self.cost_usd += cost_usd

    def record_error(self, error: str) -> None:
        """Registrar un error."""
        self.error = error
        self.completed_at = time.time()
        self.success = False

    def record_success(self) -> None:
        """Registrar éxito."""
        self.completed_at = time.time()
        self.success = True

    @property
    def total_tokens(self) -> int:
        return self.tokens_input + self.tokens_output

    @property
    def duration_seconds(self) -> float:
        if self.completed_at:
            return self.completed_at - self.started_at
        return time.time() - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "module": self.module,
            "iterations": self.iterations,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "duration_seconds": round(self.duration_seconds, 2),
            "success": self.success,
            "error": self.error,
        }


class BudgetTracker:
    """
    Rastrea el budget de tareas y tenants.

    Patrones de Hermes:
    1. Iteration budget: limitar iteraciones por tarea
    2. Cost tracking: costo en USD por tarea y tenant
    3. Budget enforcement: bloquear si excede límites
    4. Shared budget: parent + children comparten presupuesto
    """

    def __init__(
        self,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_cost_usd: float = DEFAULT_MAX_COST_USD,
    ):
        self.max_iterations = max_iterations
        self.max_cost_usd = max_cost_usd
        self._active_tasks: dict[str, TaskBudget] = {}
        self._tenant_totals: dict[str, dict[str, float]] = defaultdict(
            lambda: {"iterations": 0, "cost_usd": 0.0, "tasks": 0}
        )

    def begin_task(
        self,
        task_id: str,
        tenant_id: str,
        module: str,
    ) -> TaskBudget:
        """
        Comenzar tracking de una tarea.

        Parámetros:
            task_id: ID de la tarea
            tenant_id: ID del tenant
            module: Nombre del módulo

        Retorna:
            TaskBudget para esta tarea
        """
        budget = TaskBudget(task_id, tenant_id, module)
        self._active_tasks[task_id] = budget

        # Update tenant totals
        self._tenant_totals[tenant_id]["tasks"] += 1

        logger.info(f"Budget tracking started: task={task_id}, tenant={tenant_id}, module={module}")

        return budget

    def end_task(
        self,
        task_id: str,
        module: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        """
        Finalizar tracking de una tarea.

        Parámetros:
            task_id: ID de la tarea
            module: Nombre del módulo
            success: Si la tarea fue exitosa
            error: Mensaje de error (si failed)
        """
        budget = self._active_tasks.get(task_id)
        if not budget:
            logger.warning(f"No budget found for task {task_id}")
            return

        if success:
            budget.record_success()
        else:
            budget.record_error(error or "Unknown error")

        # Update tenant totals
        tenant_id = budget.tenant_id
        self._tenant_totals[tenant_id]["iterations"] += budget.iterations
        self._tenant_totals[tenant_id]["cost_usd"] += budget.cost_usd

        # Remove from active
        del self._active_tasks[task_id]

        logger.info(
            f"Budget tracking ended: task={task_id}, success={success}, "
            f"cost=${budget.cost_usd:.4f}, iterations={budget.iterations}"
        )

    def record_turn(
        self,
        task_id: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> bool:
        """
        Registrar un turno (llamada LLM) en una tarea.

        Verifica límites antes de registrar.

        Parámetros:
            task_id: ID de la tarea
            input_tokens: Tokens de entrada
            output_tokens: Tokens de salida
            cost_usd: Costo en USD

        Retorna:
            True si se registró, False si excedió el budget
        """
        budget = self._active_tasks.get(task_id)
        if not budget:
            return False

        # Check iteration limit
        if budget.iterations + 1 > self.max_iterations:
            logger.warning(f"Iteration budget exceeded for task {task_id}: {budget.iterations}/{self.max_iterations}")
            return False

        # Check cost limit
        if budget.cost_usd + cost_usd > self.max_cost_usd:
            logger.warning(
                f"Cost budget exceeded for task {task_id}: "
                f"current=${budget.cost_usd:.4f} + {cost_usd:.4f} > ${self.max_cost_usd:.2f}"
            )
            return False

        budget.record_turn(input_tokens, output_tokens, cost_usd)
        return True

    def get_task_budget(self, task_id: str) -> dict[str, Any] | None:
        """
        Obtener el budget actual de una tarea.

        Parámetros:
            task_id: ID de la tarea

        Retorna:
            Dict con stats de la tarea o None
        """
        budget = self._active_tasks.get(task_id)
        if not budget:
            return None
        return budget.to_dict()

    async def get_stats(self, tenant_id: str) -> dict[str, Any]:
        """
        Obtener estadísticas de uso de un tenant.

        Parámetros:
            tenant_id: ID del tenant

        Retorna:
            Dict con estadísticas de uso
        """
        totals = self._tenant_totals.get(tenant_id, {"iterations": 0, "cost_usd": 0.0, "tasks": 0})

        # Contar tareas activas
        active = sum(1 for b in self._active_tasks.values() if b.tenant_id == tenant_id)

        return {
            "tenant_id": tenant_id,
            "total_tasks": totals["tasks"],
            "active_tasks": active,
            "total_iterations": totals["iterations"],
            "total_cost_usd": round(totals["cost_usd"], 4),
        }

    def get_all_active(self) -> dict[str, dict[str, Any]]:
        """Obtener todas las tareas activas."""
        return {task_id: budget.to_dict() for task_id, budget in self._active_tasks.items()}

    async def close(self) -> None:
        """Limpiar recursos."""
        self._active_tasks.clear()
        self._tenant_totals.clear()


# Instancia global
_budget_tracker: BudgetTracker | None = None


def get_budget_tracker() -> BudgetTracker:
    """
    Obtener el gestor de presupuesto (singleton).

    Retorna:
        Instancia de BudgetTracker
    """
    global _budget_tracker
    if _budget_tracker is None:
        _budget_tracker = BudgetTracker()
    return _budget_tracker
