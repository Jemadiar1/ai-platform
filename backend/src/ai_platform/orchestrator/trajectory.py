"""
Seguimiento de trayectorias (tracking de decisiones y acciones).

Inspirado en el sistema de tracking de Hermes Agent. Rastrea cada paso
que Ragnar toma durante el procesamiento de una tarea, incluyendo
decisiones, acciones, resultados y métricas de performance.

Patrones implementados:
- Step tracking: registrar cada decisión y acción con metadata
- Trajectory lifecycle: start, add steps, complete, query
- Database persistence: guardar trayectorias completas en BD
- Latency tracking: medir tiempo de cada paso
- Cost tracking: registrar costos por paso

Uso:
    mgr = TrajectoryManager()
    trajectory = mgr.start_trajectory(session_id, tenant_id, prompt)
    trajectory.add_step(Step(step_type="route", params={"module": "ai-connect"}))
    completed = mgr.complete_trajectory(session_id)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from ai_platform.database import make_session

logger = logging.getLogger(__name__)


@dataclass
class Step:
    """
    Representa un paso individual en una trayectoria.

    Cada paso registra qué módulo/decisión se tomó, con qué
    parámetros, cuánto tiempo tomó y si hubo errores.

    Atributos:
        step_type: Tipo de paso ("route", "decompose", "execute", "cache", etc.)
        module: Módulo que ejecutó el paso (opcional)
        params: Parámetros usados en el paso
        result: Resultado del paso (truncado)
        timestamp: Cuándo se ejecutó el paso
        latency_ms: Tiempo de ejecución en milisegundos
        cost_usd: Costo en USD del paso
        error: Mensaje de error si hubo fallo
    """

    step_type: str  # "route", "decompose", "execute", "cache", "error", etc.
    module: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    result: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    latency_ms: int | None = None
    cost_usd: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convertir a dict para serialización."""
        return {
            "step_type": self.step_type,
            "module": self.module,
            "params": self.params,
            "result": self.result,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        """Crear Step desde dict deserializado."""
        ts = data.get("timestamp")
        return cls(
            step_type=data.get("step_type", "unknown"),
            module=data.get("module"),
            params=data.get("params", {}),
            result=data.get("result"),
            timestamp=datetime.fromisoformat(ts) if ts else datetime.now(UTC),
            latency_ms=data.get("latency_ms"),
            cost_usd=data.get("cost_usd"),
            error=data.get("error"),
        )


@dataclass
class Trajectory:
    """
    Representa una trayectoria completa de una interacción.

    Una trayectoria agrupa todos los pasos que Ragnar tomó
    para procesar una solicitud del usuario, desde la decisión
    inicial hasta la ejecución final.

    Atributos:
        session_id: ID de la sesión asociada
        tenant_id: ID del tenant
        user_prompt: Prompt original del usuario
        steps: Lista de pasos ejecutados
        started_at: Cuándo se inició la trayectoria
        completed_at: Cuándo se completó (None si está activa)
        tags: Etiquetas para categorizar la trayectoria
    """

    session_id: str
    tenant_id: str
    user_prompt: str
    steps: list[Step] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    tags: list[str] = field(default_factory=list)

    def add_step(self, step: Step) -> None:
        """
        Agregar un paso a la trayectoria.

        Parámetros:
            step: Paso a agregar
        """
        self.steps.append(step)
        logger.debug(f"Step added to trajectory {self.session_id}: type={step.step_type}, module={step.module}")

    @property
    def duration_ms(self) -> int | None:
        """
        Duración total de la trayectoria en milisegundos.

        Retorna:
            Duración en ms, o None si no está completada
        """
        if not self.completed_at:
            return None
        delta = self.completed_at - self.started_at
        return int(delta.total_seconds() * 1000)

    @property
    def total_cost_usd(self) -> float:
        """
        Costo total de la trayectoria en USD.

        Retorna:
            Costo total sumando todos los pasos
        """
        return sum(s.cost_usd or 0 for s in self.steps)

    @property
    def error_count(self) -> int:
        """
        Número de pasos con error.

        Retorna:
            Conteo de pasos con error
        """
        return sum(1 for s in self.steps if s.error)

    def to_dict(self) -> dict[str, Any]:
        """Convertir a dict para serialización."""
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "user_prompt": self.user_prompt[:500],
            "steps": [s.to_dict() for s in self.steps],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tags": self.tags,
            "duration_ms": self.duration_ms,
            "total_cost_usd": self.total_cost_usd,
            "error_count": self.error_count,
        }


class TrajectoryManager:
    """
    Gestiona el tracking de trayectorias de Ragnar.

    Cada interacción del usuario genera una trayectoria que
    registra todas las decisiones y acciones tomadas. Esto es
    crítico para:
    - Debugging: entender por qué un módulo fue seleccionado
    - Auditing: rastrear todas las decisiones del sistema
    - Optimization: identificar pasos lentos o costosos
    - Analytics: entender patrones de uso

    Uso:
        mgr = TrajectoryManager()
        traj = mgr.start_trajectory("sess-1", "tenant-1", "Hola")
        traj.add_step(Step(step_type="route", module="ai-connect"))
        mgr.add_step("sess-1", Step(step_type="execute", module="ai-connect"))
        completed = mgr.complete_trajectory("sess-1")
    """

    def __init__(self):
        self._current_trajectories: dict[str, Trajectory] = {}

    def start_trajectory(
        self,
        session_id: str,
        tenant_id: str,
        user_prompt: str,
        tags: list[str] | None = None,
    ) -> Trajectory:
        """
        Iniciar una nueva trayectoria.

        Se crea un nuevo objeto Trajectory y se almacena en
        memoria para tracking durante la ejecución.

        Parámetros:
            session_id: ID de la sesión
            tenant_id: ID del tenant
            user_prompt: Prompt original del usuario
            tags: Etiquetas opcionales para categorizar

        Retorna:
            Trajectory iniciada
        """
        trajectory = Trajectory(
            session_id=session_id,
            tenant_id=tenant_id,
            user_prompt=user_prompt[:500],
            tags=tags or [],
        )
        self._current_trajectories[session_id] = trajectory
        logger.info(f"Trajectory started: session={session_id}, tenant={tenant_id}, prompt_preview={user_prompt[:80]}")
        return trajectory

    def add_step(self, session_id: str, step: Step) -> None:
        """
        Agregar un paso a la trayectoria actual de una sesión.

        Si la sesión no tiene una trayectoria activa, se registra
        un warning pero no se lanza error.

        Parámetros:
            session_id: ID de la sesión
            step: Paso a agregar
        """
        if session_id in self._current_trajectories:
            self._current_trajectories[session_id].add_step(step)
        else:
            logger.warning(f"Trajectory not found for session {session_id}. Step {step.step_type} not tracked.")

    def complete_trajectory(self, session_id: str) -> Trajectory | None:
        """
        Completar y guardar una trayectoria en la base de datos.

        Marca la trayectoria como completada, calcula métricas
        finales y persiste en BD.

        Parámetros:
            session_id: ID de la sesión

        Retorna:
            Trajectory completada o None si no existía
        """
        trajectory = self._current_trajectories.pop(session_id, None)
        if trajectory:
            trajectory.completed_at = datetime.now(UTC)

            # Log resumen
            logger.info(
                f"Trajectory completed: session={session_id}, "
                f"steps={len(trajectory.steps)}, "
                f"duration_ms={trajectory.duration_ms}, "
                f"errors={trajectory.error_count}"
            )

            # Guardar en BD
            self._save_trajectory(trajectory)
        else:
            logger.warning(f"Trajectory not found for completion: session={session_id}")
        return trajectory

    def get_active_trajectory(self, session_id: str) -> Trajectory | None:
        """
        Obtener la trayectoria activa actual de una sesión.

        Parámetros:
            session_id: ID de la sesión

        Retorna:
            Trajectory activa o None
        """
        return self._current_trajectories.get(session_id)

    def _save_trajectory(self, trajectory: Trajectory) -> None:
        """
        Guardar trayectoria en BD (tabla trajectories).

        Serializa los pasos como JSON y los almacena en la base
        de datos para consulta posterior.

        Parámetros:
            trajectory: Trayectoria a guardar
        """
        try:
            with make_session() as db:
                db.execute(
                    text("""
                    INSERT INTO trajectories (
                        session_id, tenant_id, user_prompt, steps,
                        started_at, completed_at, tags
                    ) VALUES (
                        :session_id, :tenant_id, :user_prompt, :steps,
                        :started_at, :completed_at, :tags
                    )
                """),
                    {
                        "session_id": trajectory.session_id,
                        "tenant_id": trajectory.tenant_id,
                        "user_prompt": trajectory.user_prompt[:500],
                        "steps": json.dumps(
                            [s.to_dict() for s in trajectory.steps],
                            default=str,
                        ),
                        "started_at": trajectory.started_at.isoformat(),
                        "completed_at": trajectory.completed_at.isoformat() if trajectory.completed_at else None,
                        "tags": json.dumps(trajectory.tags),
                    },
                )
                db.commit()
                logger.debug(f"Trajectory saved to DB: session={trajectory.session_id}")
        except Exception as e:
            logger.error(f"Failed to save trajectory for session {trajectory.session_id}: {e}")

    def get_trajectory(self, session_id: str) -> Trajectory | None:
        """
        Obtener una trayectoria completada desde BD.

        Parámetros:
            session_id: ID de la sesión

        Retorna:
            Trajectory deserializada o None si no existe
        """
        try:
            with make_session() as db:
                result = db.execute(
                    text("""
                    SELECT steps, tags, started_at, completed_at
                    FROM trajectories
                    WHERE session_id = :session_id
                """),
                    {"session_id": session_id},
                ).first()

                if not result:
                    return None

                steps_data = json.loads(result.steps)
                steps = [Step.from_dict(s) for s in steps_data]

                tags = json.loads(result.tags) if result.tags else []
                started_at = datetime.fromisoformat(result.started_at) if result.started_at else datetime.now(UTC)
                completed_at = datetime.fromisoformat(result.completed_at) if result.completed_at else None

                trajectory = Trajectory(
                    session_id=session_id,
                    steps=steps,
                    started_at=started_at,
                    completed_at=completed_at,
                    tags=tags,
                )
                return trajectory
        except Exception as e:
            logger.error(f"Failed to load trajectory for session {session_id}: {e}")
            return None

    def list_trajectories(
        self,
        tenant_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Listar trayectorias de un tenant.

        Parámetros:
            tenant_id: ID del tenant
            limit: Máximo de resultados

        Retorna:
            Lista de dicts con resumen de trayectorias
        """
        try:
            with make_session() as db:
                result = db.execute(
                    text("""
                    SELECT session_id, user_prompt, started_at, completed_at, tags
                    FROM trajectories
                    WHERE tenant_id = :tenant_id
                    ORDER BY started_at DESC
                    LIMIT :limit
                """),
                    {
                        "tenant_id": tenant_id,
                        "limit": limit,
                    },
                ).fetchall()

                return [
                    {
                        "session_id": row.session_id,
                        "user_prompt": row.user_prompt[:100] if row.user_prompt else "",
                        "started_at": row.started_at.isoformat() if row.started_at else None,
                        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                        "tags": json.loads(row.tags) if row.tags else [],
                    }
                    for row in result
                ]
        except Exception as e:
            logger.error(f"Failed to list trajectories: {e}")
            return []

    def clear_trajectories(self, session_id: str) -> None:
        """
        Limpiar trayectorias activas de una sesión en memoria.

        Parámetros:
            session_id: ID de la sesión
        """
        if session_id in self._current_trajectories:
            del self._current_trajectories[session_id]
            logger.info(f"Cleared active trajectory for session {session_id}")


# Instancia global
_trajectory_manager: TrajectoryManager | None = None


def get_trajectory_manager() -> TrajectoryManager:
    """
    Obtener la instancia de TrajectoryManager (singleton).

    Retorna:
        Instancia de TrajectoryManager
    """
    global _trajectory_manager
    if _trajectory_manager is None:
        _trajectory_manager = TrajectoryManager()
    return _trajectory_manager
