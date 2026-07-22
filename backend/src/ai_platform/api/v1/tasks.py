"""
Endpoints de Tareas (CRUD completo).

Estos endpoints permiten:
- Crear tareas para los agentes IA
- Listar tareas del tenant actual
- Ver el estado de una tarea en tiempo real

⚠️ IMPORTANTE:
Todos los endpoints requieren:
1. Autenticación (token JWT de Clerk)
2. Multi-tenancy automático (tenant_id extraído del token)

Cada query filtra por tenant_id para asegurar que los tenants
nunca ven datos de otros tenants.

"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_platform.database import get_db_session
from ai_platform.middleware.tenant import get_current_tenant
from ai_platform.models.db import Task, Tenant
from ai_platform.schemas.task import TaskCreate, TaskPatch, TaskResponse

router = APIRouter()


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una nueva tarea",
    description="Crear una tarea que será ejecutada por un agente IA especializado",
)
def create_task(
    task_data: TaskCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db_session),
) -> TaskResponse:
    """
    Crear una nueva tarea para el módulo de IA.

    Flujo completo:
    1. El frontend (dashboard) crea una tarea con payload JSON
    2. La tarea se guarda en BD con status "pending"
    3. Se publica un evento en Redis para notificar al worker
    4. Un Celery worker consume el evento y ejecuta la tarea
    5. El worker actualiza el status en BD: running → completed/failed

    Ejemplo de payload:
    {
        "module": "ai-connect",
        "payload": {
            "action": "send_whatsapp_message",
            "to": "+521234567890",
            "message": "Hola! Tu cita es mañana a las 10am"
        },
        "priority": 0
    }

    ¿Por qué status "pending" y no "running"?
    - Porque la tarea aún no se está ejecutando
    - Un worker la leerá de la cola y cambiará el estado a "running"
    - Esto permite que el frontend muestre "tu tarea fue recibida"

    Excepciones:
    - 400: Payload inválido
    - 401: Token JWT inválido o faltante
    """
    # Validar que el módulo es soportado
    supported_modules = ["ai-connect", "ai-content", "ai-social", "ai-leads", "ai-ads", "ai-analytics", "ai-web"]
    if task_data.module not in supported_modules:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Módulo no soportado. Modules válidos: {supported_modules}"
        )

    # Crear el objeto Task en memoria con tenant_id automático
    new_task = Task(
        tenant_id=tenant.id,  # Automático del middleware
        module=task_data.module,
        status="pending",
        payload=task_data.payload,
        priority=task_data.priority,
    )

    # Guardar en base de datos
    db.add(new_task)
    db.flush()  # Flush para obtener el ID generado
    db.refresh(new_task)  # Refresh para obtener todos los campos

    # Publicar en Celery para procesamiento async
    from ai_platform.workers.task_runner import process_task

    process_task.delay(str(new_task.id), new_task.module, new_task.payload)

    return TaskResponse.model_validate(new_task)


@router.get(
    "",
    response_model=list[TaskResponse],
    summary="Listar tareas del tenant actual",
    description="Listar las tareas del tenant con filtros y paginación",
)
def list_tasks(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db_session),
    status_filter: str | None = Query(None, description="Filtrar por estado"),
    module_filter: str | None = Query(None, description="Filtrar por módulo"),
    limit: int = Query(50, ge=1, le=100, description="Máximo de resultados (1-100)"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
) -> list[TaskResponse]:
    """
    Listar tareas del tenant actual con paginación.

    ¿Por qué paginación?
    - Si un tenant tiene 10,000 tareas, no queremos traerlas todas
    - 50 tareas por página es razonable
    - Offset permite navegar: offset=0, 50, 100...

    Filtros disponibles:
    - status_filter: "pending", "running", "completed", "failed"
    - module_filter: "ai-connect", "ai-social", etc.

    Ejemplo de uso:
        GET /api/v1/tasks?status=completed&module=ai-social&limit=20&offset=0
    """
    # Construir la query base (FILTRAR POR TENANT: CRÍTICO PARA MULTI-TENANCY)
    query = select(Task).where(Task.tenant_id == tenant.id)

    # Aplicar filtros si se proporcionan
    if status_filter:
        if status_filter not in ["pending", "running", "completed", "failed", "retrying"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Estado inválido")
        query = query.where(Task.status == status_filter)

    if module_filter:
        query = query.where(Task.module == module_filter)

    # Ordenar por fecha (más recientes primero)
    query = query.order_by(Task.created_at.desc())

    # Aplicar paginación
    query = query.limit(limit).offset(offset)

    # Ejecutar query
    result = db.execute(query)
    tasks = result.scalars().all()

    return tasks


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Obtener una tarea específica",
    description="Obtener detalles de una tarea por su ID",
)
def get_task(
    task_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db_session),
) -> TaskResponse:
    """
    Obtener una tarea específica por su ID.

    CRÍTICO: Verificamos que la tarea pertenezce al tenant actual.
    Esto previene que un cliente vea tareas de otro cliente.

    Si la tarea no existe o no pertenece al tenant → 404

    Ejemplo de uso:
        GET /api/v1/tasks/550e8400-e29b-41d4-a716-446655440000
    """
    query = select(Task).where(
        Task.id == task_id,
        Task.tenant_id == tenant.id,  # CRÍTICO: solo tareas de este tenant
    )

    result = db.execute(query)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada o no tienes acceso a ella"
        )

    return TaskResponse.model_validate(task)


@router.patch(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Actualizar parcialmente una tarea",
    description="Actualizar el estado, resultado o error de una tarea",
)
def update_task(
    task_id: UUID,
    task_patch: TaskPatch,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db_session),
) -> TaskResponse:
    """
    Actualizar parcialmente una tarea.

    Se usa para:
    - Celery workers: actualizar status cuando la tarea cambia
    - Registrar resultados y errores
    - Actualizar retry_count si hubo reintentos

    Campos actualizables:
    - status: "running", "completed", "failed", etc.
    - result: resultado de la tarea
    - error: mensaje de error si falló
    - retry_count: número de reintentos

    Ejemplo:
        PATCH /api/v1/tasks/{id}
        {"status": "completed", "result": {"message": "Post publicado"}}
    """
    # Buscar la tarea (solo de este tenant)
    query = select(Task).where(Task.id == task_id, Task.tenant_id == tenant.id)

    result = db.execute(query)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    # Actualizar campos proporcionados
    update_data = task_patch.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    # Actualizar timestamps
    if "status" in update_data:
        task.updated_at = datetime.now(UTC)
        if task.status == "running" and not task.started_at:
            task.started_at = datetime.now(UTC)
        elif task.status == "completed" or task.status == "failed":
            task.completed_at = datetime.now(UTC)

    db.flush()
    db.refresh(task)

    return TaskResponse.model_validate(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una tarea",
    description="Eliminar una tarea del sistema",
)
def delete_task(
    task_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db_session),
) -> None:
    """
    Eliminar una tarea del sistema.

    Solo se pueden eliminar tareas del tenant autenticado.
    No se permite eliminar tareas de otros tenants (404).

    ⚠️ NOTA: Las tareas "running" no pueden ser eliminadas.
    """
    query = select(Task).where(
        Task.id == task_id,
        Task.tenant_id == tenant.id,
        Task.status != "running",  # No eliminar tareas en progreso
    )

    result = db.execute(query)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada o está en ejecución")

    db.delete(task)
    db.flush()

    return None
