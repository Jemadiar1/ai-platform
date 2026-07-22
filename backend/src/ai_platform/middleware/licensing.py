"""
Middleware de verificación de licenciamiento por agente.

Este módulo controla qué tenants tienen acceso a cada agente (módulo).
El acceso se define por dos capas:
  1. Plan default (free, starter, pro, enterprise)
  2. Registro manual en tenant_agents (overrides, expiraciones)

Reglas de mapeo plan -> agentes:
    free    -> ai-connect
    starter -> ai-connect + ai-analytics
    pro     -> ai-connect + ai-analytics + ai-content + ai-social
    enterprise -> todos los agentes

Prioridad:
    1. Verificar registro manual en tenant_agents
       - enabled=False -> bloqueado
       - enabled=True + expires_at pasado -> bloqueado
       - enabled=True -> permitido
    2. Si no hay registro manual, aplicar reglas de plan default
    3. Si la verificación falla por erro de BD, permitir para no bloquear

Uso desde Odin.execute():

    from ai_platform.middleware.licensing import check_agent_access

    access = check_agent_access(
        tenant_id=str(tenant.id),
        agent_name=module,
        plan=tenant.plan,
    )
    if not access["allowed"]:
        raise HTTPException(status_code=403, detail=access["reason"])
"""

from datetime import datetime, timezone

from sqlalchemy import select

from ai_platform.database import session_factory


# Mapa de agentes habilitados por plan default
PLAN_AGENTS: dict[str, set[str]] = {
    "free": {"ai-connect"},
    "starter": {"ai-connect", "ai-analytics"},
    "pro": {"ai-connect", "ai-analytics", "ai-content", "ai-social"},
    "enterprise": {
        "ai-connect",
        "ai-analytics",
        "ai-content",
        "ai-social",
        "ai-leads",
        "ai-ads",
        "ai-web",
    },
}


def check_agent_access(
    tenant_id: str,
    agent_name: str,
    plan: str = "free",
) -> dict:
    """
    Verificar si un tenant tiene acceso a un agente.

    Prioridad:
      1. Registro manual en tenant_agents (tiene precedencia sobre plan)
      2. Verificación por plan default

    Parámetros:
        tenant_id: UUID del tenant (string)
        agent_name: Nombre del agente (ej: "ai-content")
        plan: Plan actual del tenant (default: "free")

    Retorna:
        {
            "allowed": bool,
            "reason": str,
            "agent": str,
        }
    """
    agent_lower = agent_name.lower()

    _session = session_factory()
    try:
        from ai_platform.models.db import TenantAgent

        result = _session.execute(
            select(TenantAgent).where(TenantAgent.tenant_id == tenant_id, TenantAgent.agent_name == agent_lower)
        )
        record = result.scalar_one_or_none()

        if record:
            # Existe registro manual -> usar este, ignorar plan
            if not record.enabled:
                return {
                    "allowed": False,
                    "reason": f"Acceso manual revocado para agente {agent_lower}",
                    "agent": agent_lower,
                }
            if record.expires_at and record.expires_at < datetime.now(timezone.utc):
                return {
                    "allowed": False,
                    "reason": f"Acceso manual expirado para agente {agent_lower} (expiró {record.expires_at})",
                    "agent": agent_lower,
                }
            return {"allowed": True, "reason": "Acceso manual habilitado", "agent": agent_lower}

        # Paso 2: Verificar por plan default
        allowed_agents = PLAN_AGENTS.get(plan.lower(), set())
        if agent_lower not in allowed_agents:
            return {
                "allowed": False,
                "reason": f"Agente {agent_lower} no incluido en plan {plan}",
                "agent": agent_lower,
            }
        return {"allowed": True, "reason": f"Incluido en plan {plan}", "agent": agent_lower}

    except Exception as e:
        # Si falla la verificación, permitir para no bloquear el sistema
        return {"allowed": True, "reason": f"Verificación fallida (fallback): {e}", "agent": agent_lower}
    finally:
        _session.close()
