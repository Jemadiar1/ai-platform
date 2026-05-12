"""
Endpoint: Ragnar - Orquestador Inteligente.

Este endpoint expone la decisión de Ragnar al frontend.
Recibe un input del usuario y retorna:
- Qué módulo ejecutar
- Qué acción dentro del módulo
- Qué parámetros extraer
- Si necesita descomposición en múltiples módulos

Flujo:
    POST /api/v1/ragnar/decide
    {
        "prompt": "Crear una landing page y publicarla en Instagram"
    }

    Response:
    {
        "module": "ai-web",
        "action": "generate_page",
        "params": {...},
        "confidence": 0.95,
        "reasoning": "El usuario quiere crear una página web...",
        "needs_decomposition": true,
        "subtasks": [
            {"module": "ai-web", "action": "generate", "params": {...}},
            {"module": "ai-content", "action": "create_copy", "params": {...}},
            {"module": "ai-social", "action": "publish", "params": {...}}
        ],
        "session_id": "uuid"
    }

¿Por qué este endpoint?
- Permite al frontend saber qué va a pasar ANTES de crear la tarea
- El frontend puede mostrar un preview de la decisión
- El usuario puede confirmar o modificar antes de ejecutar
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ai_platform.middleware.tenant import get_current_tenant
from ai_platform.models.db import Tenant
from ai_platform.orchestrator.ragnar import get_ragnar

router = APIRouter()


class RagnarDecideRequest(BaseModel):
    """
    Request para el endpoint /ragnar/decide.
    """

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Input del usuario (ej: 'Crear una landing page para mi negocio')",
    )
    session_id: str | None = Field(
        default=None, description="ID de sesión existente (opcional, se crea nueva si no se proporciona)"
    )


class RagnarDecideResponse(BaseModel):
    """
    Response del endpoint /ragnar/decide.
    """

    module: str
    action: str
    params: dict[str, Any]
    confidence: float
    reasoning: str
    needs_decomposition: bool
    subtasks: list[dict[str, Any]]
    session_id: str
    status: str = "decision_made"


@router.post(
    "/decide",
    response_model=RagnarDecideResponse,
    status_code=status.HTTP_200_OK,
    summary="Ragnar decide qué módulo ejecutar",
    description="El orquestador analiza el input del usuario y decide qué módulo IA debe actuar",
)
def ragnar_decide(
    request: RagnarDecideRequest,
    tenant: Tenant = Depends(get_current_tenant),
):
    """
    Endpoint principal de Ragnar.

    Este es el cerebro de AI Platform. Analiza el input del usuario
    y decide qué módulo especializado debe ejecutar la tarea.

    Flujo:
    1. Sanitizar input contra inyección de prompts
    2. Cargar contexto de sesión (frozen snapshot)
    3. Escanear memoria relevante
    4. Consultar LLM (OpenRouter) para routing
    5. Si necesita descomposición → descomponer en subtasks
    6. Extraer parámetros del módulo
    7. Registrar observabilidad
    8. Retornar decisión

    Ejemplo de uso:
        POST /api/v1/ragnar/decide
        {
            "prompt": "Enviar un mensaje de WhatsApp a +51999999999: Hola, esto es una oferta",
            "session_id": "optional-session-id"
        }

    Response:
        {
            "module": "ai-connect",
            "action": "send_whatsapp",
            "params": {"phone": "+51999999999", "message": "Hola..."},
            "confidence": 0.98,
            "reasoning": "El usuario quiere enviar un mensaje por WhatsApp...",
            "needs_decomposition": false,
            "subtasks": [],
            "session_id": "uuid"
        }
    """
    try:
        ragnar = get_ragnar()

        decision = ragnar.decide(
            prompt=request.prompt,
            tenant_id=str(tenant.id),
            session_id=request.session_id,
        )

        return RagnarDecideResponse(
            module=decision["module"],
            action=decision["action"],
            params=decision["params"],
            confidence=decision["confidence"],
            reasoning=decision["reasoning"],
            needs_decomposition=decision["needs_decomposition"],
            subtasks=decision.get("subtasks", []),
            session_id=decision["session_id"],
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error en el orquestador Ragnar: {e!s}"
        ) from None
