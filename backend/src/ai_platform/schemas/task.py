"""
Schemas Pydantic para Tareas.

Los schemas Pydantic son la capa de validación de FastAPI.
Separados en schemas de creación y respuesta para:
- No exponer campos internos (created_at, status) al crear
- Controlar exactamente qué campos se devuelven

Ejemplo de flujo:
    # frontend envía:  {"module": "ai-social", "payload": {"action": "post"}, "priority": 1}
    # TaskCreate valida: tiene module? tiene payload?
    # El endpoint crea la tarea en BD
    # TaskResponse devuelve: {"id": "...", "module": "ai-social", ...}
"""

from pydantic import BaseModel, Field
from typing import Optional, Any
from uuid import UUID
from datetime import datetime


class TaskCreate(BaseModel):
    """Schema para crear una tarea"""
    module: str = Field(
        description="Módulo que ejecutará la tarea",
        # Solo permite módulos válidos
        pattern=r"^(ai-connect|ai-content|ai-social|ai-leads|ai-ads|ai-analytics|ai-web)$"
    )
    payload: dict[str, Any] = Field(
        description="Datos de la tarea en formato JSON",
        max_length=65536
    )
    priority: int = Field(
        default=0,
        ge=0,
        le=2,
        description="Prioridad: 0=normal, 1=alta, 2=critical"
    )


class TaskPatch(BaseModel):
    """Schema para actualizar parcialmente una tarea"""
    status: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: Optional[int] = None


class TaskResponse(BaseModel):
    """Schema para responder datos de una tarea"""
    id: UUID
    tenant_id: UUID
    module: str
    status: str
    payload: dict[str, Any]
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0
    priority: int = 0
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}
