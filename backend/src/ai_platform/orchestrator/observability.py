"""
Observabilidad para el orquestador Ragnar.

Registra cada decisión crítica del orquestador para:
- Debugging y troubleshooting
- Análisis de patrones de uso
- Auditoría y compliance
- Optimización de costos

Patrones:
- Decision logging: registrar cada decision de routing
- Metric collection: recopilar métricas por módulo
- Trace correlation: correlacionar decisiones con resultados

Uso:
    logger = DecisionLogger()
    logger.log_decision({
        "tenant_id": "...",
        "prompt": "...",
        "module": "ai-connect",
        "reasoning": "...",
    })
"""

import json
import logging
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

# Loggers separados para different types de observabilidad
DECISION_LOGGER = logging.getLogger("ai_platform.orchestrator.decisions")
METRIC_LOGGER = logging.getLogger("ai_platform.orchestrator.metrics")
ERROR_LOGGER = logging.getLogger("ai_platform.orchestrator.errors")


class DecisionLogger:
    """
    Log de decisiones del orquestador.

    Registra CADA decisión de routing con metadata completa.
    Esto es crítico para:
    - Debugging: entender por qué Ragnar eligió un módulo
    - Análisis: identificar patrones de usage
    - Optimización: ver qué módulos se usan más
    - Auditoría: rastrear todas las decisiones del sistema
    """

    def __init__(self):
        self._decision_count = 0
        self._module_counts: Dict[str, int] = defaultdict(int)
        self._error_count = 0

    def log_decision(self, decision: Dict[str, Any]) -> None:
        """
        Registrar una decisión de routing.

        Cada decisión incluye:
        - tenant_id: quién hizo la petición
        - prompt: lo que el usuario dijo (truncado)
        - module: qué módulo eligió Ragnar
        - confidence: score de confianza
        - reasoning: por qué tomó esa decisión

        Parámetros:
            decision: Dict con todos los datos de la decisión
        """
        self._decision_count += 1
        module = decision.get("module", "unknown")
        self._module_counts[module] += 1

        # Log en formato JSON para log-aggregators (Grafana/Loki)
        DECISION_LOGGER.info(
            json.dumps({
                "event": "routing_decision",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "decision_id": f"dec_{self._decision_count}",
                **decision,
            }, default=str)
        )

        # Log de resumen para desarrolladores
        logger.debug(
            f"[Ragnar Decision #{self._decision_count}] "
            f"module={module}, confidence={decision.get('confidence', 0):.2f}, "
            f"reasoning={decision.get('reasoning', '')[:100]}"
        )

    def log_error(self, error: Dict[str, Any]) -> None:
        """
        Registrar un error crítico del orquestador.

        Parámetros:
            error: Dict con datos del error
        """
        self._error_count += 1
        ERROR_LOGGER.error(
            json.dumps({
                "event": "orchestrator_error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error_id": f"err_{self._error_count}",
                **error,
            }, default=str)
        )

    def log_metric(self, metric: Dict[str, Any]) -> None:
        """
        Registrar una métrica de uso.

        Parámetros:
            metric: Dict con datos de la métrica
        """
        METRIC_LOGGER.info(
            json.dumps({
                "event": "usage_metric",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **metric,
            }, default=str)
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        Obtener estadísticas de decisiones.

        Retorna:
            Dict con conteos por módulo y total de decisiones
        """
        return {
            "total_decisions": self._decision_count,
            "total_errors": self._error_count,
            "by_module": dict(self._module_counts),
        }


class Observation:
    """
    Representa una observación individual.
    """

    def __init__(
        self,
        event_type: str,
        data: Dict[str, Any],
    ):
        self.timestamp = datetime.now(timezone.utc)
        self.event_type = event_type
        self.data = data
        self.trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "trace_id": self.trace_id,
            "data": self.data,
        }


class MetricsCollector:
    """
    Colecta métricas de uso del orquestador.

    Métricas principales:
    - Decisions per tenant
    - Model usage (cuántas veces se usó cada modelo)
    - Routing latency (tiempo de decisión)
    - Module usage distribution
    """

    def __init__(self):
        self._events: List[Observation] = []
        self._max_history = 10000  # Mantener últimas 10K entradas

    def record_decision(
        self,
        tenant_id: str,
        module: str,
        latency_ms: float,
        model: str,
    ) -> None:
        """
        Registrar una decisión de routing.

        Parámetros:
            tenant_id: ID del tenant
            module: Módulo elegido
            latency_ms: Tiempo en ms de la decisión
            model: Modelo LLM usado
        """
        observation = Observation(
            event_type="routing_decision",
            data={
                "tenant_id": tenant_id,
                "module": module,
                "latency_ms": round(latency_ms, 2),
                "model": model,
            },
        )
        self._events.append(observation)

        # Log como métrica
        METRIC_LOGGER.info(
            json.dumps({
                "event": "routing_decision",
                "tenant_id": tenant_id,
                "module": module,
                "latency_ms": round(latency_ms, 2),
                "model": model,
            })
        )

    def record_task_result(
        self,
        tenant_id: str,
        module: str,
        success: bool,
        cost_usd: float,
        tokens: int,
    ) -> None:
        """
        Registrar resultado de una tarea ejecutada.

        Parámetros:
            tenant_id: ID del tenant
            module: Módulo ejecutado
            success: Si fue exitoso
            cost_usd: Costo en USD
            tokens: Tokens consumidos
        """
        observation = Observation(
            event_type="task_result",
            data={
                "tenant_id": tenant_id,
                "module": module,
                "success": success,
                "cost_usd": round(cost_usd, 6),
                "tokens": tokens,
            },
        )
        self._events.append(observation)

        METRIC_LOGGER.info(
            json.dumps({
                "event": "task_result",
                "tenant_id": tenant_id,
                "module": module,
                "success": success,
                "cost_usd": round(cost_usd, 6),
                "tokens": tokens,
            })
        )

    def get_tenant_metrics(self, tenant_id: str) -> Dict[str, Any]:
        """
        Obtener métricas agregadas de un tenant.

        Parámetros:
            tenant_id: ID del tenant

        Retorna:
            Dict con métricas agregadas
        """
        tenant_events = [
            e for e in self._events
            if e.data.get("tenant_id") == tenant_id
        ]

        module_counts = defaultdict(int)
        total_latency = 0.0
        latency_count = 0
        total_cost = 0.0
        total_tokens = 0
        success_count = 0
        fail_count = 0

        for event in tenant_events:
            data = event.data

            module = data.get("module")
            if module:
                module_counts[module] += 1

            if "latency_ms" in data:
                total_latency += data["latency_ms"]
                latency_count += 1

            if "cost_usd" in data:
                total_cost += data["cost_usd"]

            if "tokens" in data:
                total_tokens += data["tokens"]

            if "success" in data:
                if data["success"]:
                    success_count += 1
                else:
                    fail_count += 1

        return {
            "total_events": len(tenant_events),
            "module_distribution": dict(module_counts),
            "success_rate": round(success_count / (success_count + fail_count), 3) if (success_count + fail_count) > 0 else 0,
            "avg_latency_ms": round(total_latency / latency_count, 2) if latency_count > 0 else 0,
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
        }

    def get_system_metrics(self) -> Dict[str, Any]:
        """
        Obtener métricas del sistema completo.

        Retorna:
            Dict con métricas globales
        """
        module_counts = defaultdict(int)
        total_cost = 0.0
        total_tokens = 0

        for event in self._events:
            data = event.data
            module = data.get("module")
            if module:
                module_counts[module] += 1
            if "cost_usd" in data:
                total_cost += data["cost_usd"]
            if "tokens" in data:
                total_tokens += data["tokens"]

        return {
            "total_events": len(self._events),
            "module_distribution": dict(module_counts),
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
            "historical_entries": len(self._events),
        }

    def clear_history(self) -> None:
        """Limpiar historial de métricas."""
        self._events.clear()


# Instancias globales
_decision_logger = DecisionLogger()
_metrics_collector = MetricsCollector()

# Public API
log_decision = _decision_logger.log_decision
log_error = _decision_logger.log_error
log_metric = _decision_logger.log_metric
get_decision_stats = _decision_logger.get_stats
record_decision_metric = _metrics_collector.record_decision
record_task_result_metric = _metrics_collector.record_task_result
get_tenant_metrics = _metrics_collector.get_tenant_metrics
get_system_metrics = _metrics_collector.get_system_metrics
