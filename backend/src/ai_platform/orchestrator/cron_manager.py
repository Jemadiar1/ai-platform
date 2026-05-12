"""
Gestor de tareas programadas (cron jobs) para Ragnar.

Inspirado en Hermes Agent's cron scheduler.
Permite programar tareas automáticas por tenant.

Patrones de Hermes aplicados:
- Scheduler que verifica periódicamente jobs vencidos
- Jobs programados por tenant con diferentes frecuencias
- Tracking de ejecuciones (last_run, run_count)
- Handler async/sync soportado
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from uuid import uuid4

logger = logging.getLogger(__name__)


class CronSchedule:
    """Clases de frecuencia para cron jobs."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    CUSTOM = "custom"

    INTERVALS: ClassVar[dict] = {
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
    }


@dataclass
class CronJob:
    """Un cron job programado."""

    job_id: str
    tenant_id: str
    schedule: str
    next_run: datetime
    handler: Callable  # Función async a ejecutar
    active: bool = True
    last_run: datetime | None = None
    run_count: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def update_next_run(self):
        """Actualizar la próxima ejecución basada en el intervalo."""
        interval = CronSchedule.INTERVALS.get(self.schedule)
        if interval:
            self.next_run = datetime.now(UTC) + interval

    def get_next_run_iso(self) -> str:
        """Retornar próxima ejecución en formato ISO."""
        return self.next_run.isoformat()


class CronManager:
    """
    Gestiona cron jobs para tenants.

    Patrón de Hermes Agent: scheduler que verifica periódicamente
    qué jobs están vencidos y los ejecuta.
    """

    def __init__(self):
        self._jobs: list[CronJob] = []
        self._run_interval_seconds = 60  # Verificar cada 60 segundos
        self._scheduler_task: asyncio.Task | None = None

    def add_job(
        self,
        tenant_id: str,
        schedule: str,
        handler: Callable,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """
        Registrar un nuevo cron job.

        El job se programa con la frecuencia especificada
        y comienza a ejecutarse inmediatamente.

        Parámetros:
            tenant_id: ID del tenant asociado
            schedule: Frecuencia ("hourly", "daily", "weekly")
            handler: Función async a ejecutar
            meta: Metadatos adicionales del job

        Retorna:
            job_id del job registrado
        """
        job = CronJob(
            job_id=str(uuid4()),
            tenant_id=tenant_id,
            schedule=schedule,
            next_run=datetime.now(UTC),
            handler=handler,
            active=True,
            meta=meta or {},
        )
        self._jobs.append(job)
        logger.info(f"Cron job registered: {job.job_id} (tenant: {tenant_id}, schedule: {schedule})")
        return job.job_id

    def remove_job(self, job_id: str) -> bool:
        """
        Desactivar un cron job.

        Parámetros:
            job_id: ID del job a desactivar

        Retorna:
            True si se encontró y desactivó, False si no existe
        """
        for job in self._jobs:
            if job.job_id == job_id:
                job.active = False
                return True
        return False

    async def start_scheduler(self):
        """
        Iniciar el scheduler que verifica jobs pendientes.

        Este método corre en un loop infinito verificando
        cada _run_interval_seconds si hay jobs vencidos.
        """
        logger.info("Cron scheduler started")
        while True:
            await self._check_due_jobs()
            await asyncio.sleep(self._run_interval_seconds)

    async def _check_due_jobs(self):
        """Verificar y ejecutar cron jobs vencidos."""
        now = datetime.now(UTC)
        for job in self._jobs:
            if job.active and job.next_run <= now:
                try:
                    if asyncio.iscoroutinefunction(job.handler):
                        await job.handler()
                    else:
                        job.handler()
                    job.last_run = now
                    job.run_count += 1
                    job.update_next_run()
                    logger.info(f"Cron job executed: {job.job_id} (run #{job.run_count})")
                except Exception as e:
                    logger.error(f"Cron job {job.job_id} failed: {e}")

    def list_jobs(self, tenant_id: str | None = None) -> list[dict]:
        """
        Listar todos los cron jobs (o de un tenant específico).

        Parámetros:
            tenant_id: Si se proporciona, filtra por tenant

        Retorna:
            Lista de dicts con info de cada job
        """
        result = []
        for job in self._jobs:
            if tenant_id and job.tenant_id != tenant_id:
                continue
            result.append(
                {
                    "job_id": job.job_id,
                    "tenant_id": job.tenant_id,
                    "schedule": job.schedule,
                    "next_run": job.get_next_run_iso(),
                    "active": job.active,
                    "last_run": job.last_run.isoformat() if job.last_run else None,
                    "run_count": job.run_count,
                    "meta": job.meta,
                }
            )
        return result


# Instancia global
_cron_manager: CronManager | None = None


def get_cron_manager() -> CronManager:
    """
    Obtener gestor de cron jobs (singleton).

    Retorna:
        Instancia de CronManager
    """
    global _cron_manager
    if _cron_manager is None:
        _cron_manager = CronManager()
    return _cron_manager
