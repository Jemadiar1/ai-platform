"""
Endpoints de Health Check.

Estos endpoints se usan para:
- Docker health checks: verificar que el contenedor está vivo
- Load balancers: verificar que el servicio está disponible
- Prometheus: métricas de uptime y latencia
- Debug: verificar que la API responde

Cada endpoint debe devolver 200 OK con un JSON simple.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

router = APIRouter()


@router.get(
    "/ping",
    summary="Ping simple",
    description="Endpoint más simple para verificar que la API está viva",
    response_description="Mensaje de respuesta",
)
def ping() -> dict[str, Any]:
    """
    Endpoint de ping básico.

    Responde con un JSON simple. Se usa para:
    - Verificar rápidamente que el servicio está disponible
    - Health checks de Docker/Kubernetes
    - Monitor de infraestructura

    Uso:
        curl http://localhost:4000/api/v1/ping
        # {"status": "ok", "service": "ai-platform-backend", "timestamp": "..."}
    """
    return {
        "status": "ok",
        "service": "ai-platform-backend",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get(
    "/health",
    summary="Health check completo",
    description="Verifica que la API y sus dependencias (BD) están operativas",
    response_description="Estado de cada componente",
)
def health_check() -> dict[str, Any]:
    """
    Health check completo.

    Verifica que:
    1. La API está respondiendo
    2. La base de datos está accesible (si está disponible)

    Devuelve el estado de cada componente.
    Si la BD no está disponible, devuelve 200 con database: "error"
    ya que esto es desarrollo y no tiene DB real.

    Uso:
        curl http://localhost:4000/api/v1/health
        # {"status": "ok", "components": {"database": "error"}}
    """
    from ai_platform.database import engine

    components = {}
    overall_status = "ok"

    # Verificar conexión a PostgreSQL
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "error"
        # En desarrollo no es crítico que la BD no esté disponible
        overall_status = "degraded"

    # Devolver estado
    return {
        "status": overall_status,
        "components": components,
        "timestamp": datetime.now(UTC).isoformat(),
    }
