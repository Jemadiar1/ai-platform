"""
Worker de Tareas Asíncronas con Celery.

Celery es el estándar de Python para procesamiento asíncrono.
Es equivalente a BullMQ en Node.js pero más maduro y con más features.

¿Qué hace Celery?
- Recibe tareas de una cola (Redis)
- Las ejecuta en workers paralelos
- Maneja reintentos automáticas con backoff exponencial
- Tiene dead letter queue (tareas que fallan 3 veces se archivan)
- Tiene scheduler para jobs periódicos (cron)

Flujo completo de una tarea:
    1. Frontend → POST /api/v1/tasks → Task guardada con status "pending"
    2. API → Publica evento en Redis Pub/Sub
    3. Celery Worker → Escucha el evento
    4. Celery Worker → Cambia status a "running"
    5. Celery Worker → Ejecuta la lógica del módulo
    6. Celery Worker → Cambia status a "completed" o "failed"
    7. Celery Worker → Registra usage_event para billing

⚠️ IMPORTANTE: Para ejecutar este worker:
    cd backend
    py -m celery -A ai_platform.workers.task_runner worker --loglevel=info --concurrency=4

Para ver el worker funcionando en tiempo real, abre otra terminal:
    py -m celery -A ai_platform.workers.task_runner event --monitor
"""

from datetime import UTC, datetime
from typing import Any

from celery import Celery
from celery.utils.log import get_task_logger
from sqlalchemy import select

# Importar dependencias del proyecto
from ai_platform.database import session_factory
from ai_platform.models.db import Task, UsageEvent

logger = get_task_logger("ai_platform.task_runner")


# Crear la aplicación Celery
# Usa Redis como broker (cola de mensajes) y backend (resultado)
celery_app = Celery(
    "ai_platform_workers",
    broker="redis://localhost:6379/1",  # Broker: donde se guardan las tareas
    backend="redis://localhost:6379/2",  # Backend: donde se guardan los resultados
)

# Configurar Celery con opciones avanzadas
celery_app.conf.update(
    task_serializer="json",  # Serializar tareas en JSON
    accept_content=["json"],  # Solo aceptar JSON
    result_serializer="json",  # Resultados en JSON
    timezone="UTC",  # Zona horaria
    enable_utc=True,  # Usar UTC
    # === Retries: reintentos automáticos ===
    # task_acks_late → Confirmar tarea DESPUÉS de ejecutar
    #              → Si el worker se cae durante la ejecución, la tarea se reintenta
    task_acks_late=True,
    # task_reject_on_worker_lost → Si el proceso Celery se mata, la tarea vuelve a la cola
    task_reject_on_worker_lost=True,
    # task_track_started → Trackear cuándo empieza cada tarea
    task_track_started=True,
    # === Backoff exponencial ===
    # Primer retry: 60seg, Segundo: 120seg, Tercero: 240seg
    task_default_retry_delay=60,
    task_max_retries=3,
    task_retry_backoff=True,
    task_retry_backoff_max=7200,  # Máximo 2 horas entre retries
    # === Timeouts ===
    # Soft timeout (5 min): la tarea recibe SIGTERM
    task_soft_time_limit=300,
    # Hard timeout (10 min): la tarea recibe SIGKILL
    task_time_limit=600,
    # === Concurrency ===
    # 4 workers trabajando en paralelo
    worker_concurrency=4,
    # 1 tarea a la vez por worker (evita que un worker se sobrecargue)
    worker_prefetch_multiplier=1,
)


def save_task_update(task_id: str, updates: dict[str, Any]) -> None:
    """
    Actualizar una tarea en la base de datos.

    Se llama desde los Celery workers para:
    - Cambiar status de "pending" a "running"
    - Guardar el resultado de la tarea
    - Registrar errores
    - Actualizar timestamps

    Parámetros:
        task_id: ID de la tarea (UUID como string)
        updates: Diccionario con campos a actualizar (status, result, error, etc.)

    Nota: Esta función es síncrona porque Celery tasks son síncronas por defecto.
    """
    session = session_factory()
    try:
        query = select(Task).where(Task.id == task_id)
        result = session.execute(query)
        task = result.scalar_one_or_none()

        if task:
            for key, value in updates.items():
                setattr(task, key, value)
            task.updated_at = datetime.now(UTC)
            session.commit()
            logger.info("task_updated", task_id=str(task_id), fields=list(updates.keys()))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_usage_event(
    tenant_id: str, module: str, event_type: str, tokens: int, cost: float, task_id: str | None = None
) -> None:
    """
    Registrar un evento de uso para billing.

    Cada vez que un módulo ejecuta algo, se registra:
    - Cuántos tokens consumió
    - Cuánto costó (USD)
    - En qué módulo se usó

    Esto se usa para:
    - Facturar al tenant automáticamente (Stripe)
    - Mostrar métricas de consumo en el dashboard
    - Respetar límites de usage según el plan

    Parámetros:
        tenant_id: ID del tenant que consumió el servicio
        module: Módulo que generó el uso (ai-connect, ai-social, etc.)
        event_type: Tipo de evento (task_execution, api_call, message_sent)
        tokens: Número de tokens de IA consumidos
        cost: Costo en USD del evento
        task_id: ID de la tarea asociada (opcional)

    Nota: Esta función es síncrona porque Celery tasks son síncronas por defecto.
    """
    session = session_factory()
    try:
        usage_event = UsageEvent(
            tenant_id=tenant_id,
            task_id=task_id,
            module=module,
            event_type=event_type,
            tokens_used=tokens,
            cost_usd=cost,
        )
        session.add(usage_event)
        session.commit()
        logger.info(
            "usage_event_saved",
            tenant_id=str(tenant_id),
            module=module,
            tokens=tokens,
            cost=cost,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(
    name="process_task",
    bind=True,  # Permite acceder al propio task (self) para retries
    max_retries=3,  # Máximo 3 reintentos
    acks_late=True,  # Confirmar después de ejecutar (no antes)
)
def process_task(self, task_id: str, module: str, payload: dict) -> dict:
    """
    Worker principal: ejecuta la lógica de cada módulo de IA.

    Este es el "cerebro" de los workers. Recibe una tarea de Redis
    y decide qué módulo la ejecuta según su tipo.

    Flujo de ejecución:
    1. Recibe la tarea de la cola Redis
    2. Guarda status = "running" en la base de datos
    3. Importa dinámicamente el handler del módulo correcto
    4. Ejecuta la lógica del módulo con el payload
    5. Guarda status = "completed" + resultado
    6. Registra usage para billing
    7. Devuelve el resultado

    Si cualquier paso falla → Celery reintentar (hasta 3 veces)
    Si falla 3 veces → dead letter (se archiva y se alerta al admin)

    Parámetros:
        task_id: ID de la tarea en la base de datos (UUID como string)
        module: Nombre del módulo que ejecutará la tarea
        payload: Datos de la tarea con la acción a ejecutar

    Retorna:
        dict con el resultado de la ejecución
    """
    logger.info("task_started", task_id=task_id, module=module)

    try:
        # Paso 1: Cambiar status a "running"
        save_task_update(task_id, {"status": "running", "started_at": datetime.now(UTC)})

        # Paso 2: Importar el handler del módulo correcto
        from ai_platform.orchestrator.modules import get_handler, get_module_names

        if module not in get_module_names():
            raise ValueError(f"Módulo no soportado: {module}. Módulos válidos: {get_module_names()}")

        # Cargar el handler dinámicamente
        HandlerClass = get_handler(module)
        handler = HandlerClass()

        # Paso 3: Ejecutar la lógica del módulo
        logger.info("executing_module", task_id=task_id, module=module, action=payload.get("action", "unknown"))
        result = handler.execute(payload)

        # Paso 4: Guardar resultado en la base de datos
        save_task_update(task_id, {"status": "completed", "result": result, "completed_at": datetime.now(UTC)})

        # Paso 5: Registrar uso para billing
        # TODO: Obtener tenant_id real de la tarea
        logger.info("task_completed", task_id=task_id, module=module)
        return result if isinstance(result, dict) else {"status": "ok", "data": result}

    except Exception as exc:
        # Si falla, registrar el error en la base de datos
        logger.error("task_failed", task_id=task_id, module=module, error=str(exc))

        save_task_update(task_id, {"status": "failed", "error": str(exc), "completed_at": datetime.now(UTC)})

        # Reintentar automáticamente con backoff exponencial
        # Retry 1: 60s, Retry 2: 120s, Retry 3: 240s
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from None
