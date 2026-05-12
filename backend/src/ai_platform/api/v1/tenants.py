"""
Endpoints de Tenants.

Gestión de tenants (clientes) del sistema.

⚠️ EN PRODUCCIÓN, los tenants se crean principalmente por Clerk.
Estos endpoints son para:
- Crear un tenant asociado a un usuario de Clerk
- Ver información del tenant actual
- Actualizar configuración del tenant

"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_platform.database import get_db_session
from ai_platform.middleware.tenant import get_current_tenant
from ai_platform.models.db import Tenant
from ai_platform.schemas.tenant import TenantCreate, TenantResponse

router = APIRouter()


@router.get(
    "/me",
    response_model=TenantResponse,
    summary="Obtener tenant actual",
    description="Obtener información del tenant del usuario autenticado",
)
def get_current_tenant_info(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db_session),
):
    """
    Obtener información del tenant actual.

    Este endpoint permite al frontend conocer:
    - Nombre del tenant
    - Plan contratado
    - Configuración actual

    Es el primer endpoint que llama el dashboard después de login.
    """
    return TenantResponse.model_validate(tenant)


@router.post(
    "",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un nuevo tenant",
    description="Crear un tenant (generalmente hecho por Clerk post-signup)",
)
def create_tenant(
    tenant_data: TenantCreate,
    db: Session = Depends(get_db_session),
):
    """
    Crear un nuevo tenant.

    Normalmeente se llama después de que un usuario se registra en Clerk.
    Clerk webhook dispara la creación del tenant.

    El slug debe ser único (no puede haber dos "mi-empresa").
    Si ya existe un tenant con ese slug, retorna 409 Conflict.
    """
    # Verificar que el slug no exista
    existing = db.execute(select(Tenant).where(Tenant.slug == tenant_data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"El slug '{tenant_data.slug}' ya está en uso")

    # Crear el tenant
    new_tenant = Tenant(
        name=tenant_data.name,
        slug=tenant_data.slug,
        plan=tenant_data.plan,
        billing_email=tenant_data.billing_email,
    )

    db.add(new_tenant)
    db.flush()
    db.refresh(new_tenant)

    return TenantResponse.model_validate(new_tenant)
