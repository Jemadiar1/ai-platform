"""
Schemas Pydantic para Tenants.

Un "tenant" es cada cliente que contrata NeuralCrew Labs.
Cada tenant tiene sus propias tareas, usuarios, datos y configuración.

¿Por qué schemas separados?
- TenantCreate: campos que el cliente envía al crear un tenant
- TenantResponse: datos que devolvemos al consultar un tenant
- Esto evita exponer fields internos como created_at o is_active
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Any
from uuid import UUID
from datetime import datetime


class TenantCreate(BaseModel):
    """Schema para crear un tenant"""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)
    plan: str = Field(default="starter")
    billing_email: Optional[EmailStr] = None


class TenantResponse(BaseModel):
    """Schema para responder datos de un tenant"""
    id: UUID
    name: str
    slug: str
    plan: str
    billing_email: Optional[str] = None
    settings: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}
