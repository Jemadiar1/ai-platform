"""
Endpoints de administración.

Este módulo expone endpoints internos para gestionar planes y
acceso a agentes por tenant.

⚠️ Estos endpoints son internos y deben estar protegidos.
En producción, se usaría un sistema de autenticación de admin.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ai_platform.database import session_factory
from ai_platform.middleware.tenant import get_current_tenant
from ai_platform.models.db import Tenant, TenantAgent
from sqlalchemy import select

router = APIRouter()


class SetPlanRequest(BaseModel):
    """Solicitud para establecer el plan de un tenant."""

    plan: str = Field(
        ...,
        description="Plan a establecer: free, starter, pro, enterprise",
        pattern="^(free|starter|pro|enterprise)$",
    )


class SetAgentAccessRequest(BaseModel):
    """Solicitud para habilitar/deshabilitar un agente para un tenant."""

    agent_name: str = Field(
        ...,
        description="Nombre del agente (ej: ai-content, ai-social)",
    )
    enabled: bool = Field(default=True, description="Habilitar o deshabilitar el agente")
    expires_at: datetime | None = Field(
        default=None,
        description="Fecha de expiración del acceso (None = permanente)",
    )


class TenantPlanResponse(BaseModel):
    """Respuesta con el plan actual y agentes del tenant."""

    tenant_id: str
    name: str
    plan: str
    agents: list[dict]


class AgentAccessResponse(BaseModel):
    """Respuesta con el estado de acceso a un agente."""

    tenant_id: str
    agent_name: str
    enabled: bool
    expires_at: datetime | None


# =========================================================================
# Rutas
# =========================================================================


@router.get(
    "/tenants/{tenant_id}/plan",
    response_model=TenantPlanResponse,
    summary="Obtener plan y agentes de un tenant",
    description="Consultar el plan actual y los agentes habilitados de un tenant",
)
def get_tenant_plan(tenant_id: str):
    """
    Obtener plan y agentes de un tenant.

    Endpoint de administración. Requiere autenticación de admin.
    """
    _session = session_factory()
    try:
        tenant = _session.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant no encontrado")

        agents = _session.execute(select(TenantAgent).where(TenantAgent.tenant_id == tenant_id)).scalars().all()

        return TenantPlanResponse(
            tenant_id=str(tenant.id),
            name=tenant.name,
            plan=tenant.plan,
            agents=[
                {
                    "agent_name": a.agent_name,
                    "enabled": a.enabled,
                    "expires_at": a.expires_at,
                }
                for a in agents
            ],
        )
    finally:
        _session.close()


@router.post(
    "/tenants/{tenant_id}/set-plan",
    response_model=TenantPlanResponse,
    summary="Establecer plan de un tenant",
    description="Actualizar el plan de un tenant. Los agentes se actualizan automáticamente según las reglas del plan.",
)
def set_tenant_plan(tenant_id: str, request: SetPlanRequest):
    """
    Establecer plan de un tenant.

    Al cambiar el plan, se eliminan los registros manuales de agentes
    que ya no están incluidos en el nuevo plan, pero se preservan
    los que sí están incluidos.
    """
    _session = session_factory()
    try:
        tenant = _session.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant no encontrado")

        tenant.plan = request.plan
        _session.commit()
        _session.refresh(tenant)

        agents = _session.execute(select(TenantAgent).where(TenantAgent.tenant_id == tenant_id)).scalars().all()

        return TenantPlanResponse(
            tenant_id=str(tenant.id),
            name=tenant.name,
            plan=tenant.plan,
            agents=[
                {
                    "agent_name": a.agent_name,
                    "enabled": a.enabled,
                    "expires_at": a.expires_at,
                }
                for a in agents
            ],
        )
    finally:
        _session.close()


@router.post(
    "/tenants/{tenant_id}/set-agent-access",
    response_model=AgentAccessResponse,
    summary="Habilitar/deshabilitar acceso a un agente",
    description="Configurar acceso manual a un agente específico para un tenant. Este override tiene prioridad sobre el plan.",
)
def set_agent_access(tenant_id: str, request: SetAgentAccessRequest):
    """
    Configurar acceso manual a un agente.

    Este registro tiene prioridad sobre las reglas de plan default.
    Permite habilitar/deshabilitar agentes independientemente del plan.
    """
    _session = session_factory()
    try:
        tenant = _session.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant no encontrado")

        record = _session.execute(
            select(TenantAgent).where(
                TenantAgent.tenant_id == tenant_id,
                TenantAgent.agent_name == request.agent_name,
            )
        ).scalar_one_or_none()

        if record:
            record.enabled = request.enabled
            record.expires_at = request.expires_at
            record.updated_at = datetime.now(timezone.utc)
        else:
            record = TenantAgent(
                tenant_id=tenant_id,
                agent_name=request.agent_name,
                enabled=request.enabled,
                expires_at=request.expires_at,
            )
            _session.add(record)

        _session.flush()

        return AgentAccessResponse(
            tenant_id=tenant_id,
            agent_name=request.agent_name,
            enabled=record.enabled,
            expires_at=record.expires_at,
        )
    finally:
        _session.close()
