"""
API interna de investigación web.

Endpoints para que Odin y otros módulos invoquen investigación web.
No es un módulo vendible: es una capacidad interna de la plataforma.

Multi-tenant: todos los endpoints requieren tenant_id válido.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from ai_platform.services.web_research_service import (
    web_research_service,
)

router = APIRouter()


@router.post("/fetch")
async def api_fetch_url(
    url: str = Query(..., description="URL a investigar (solo http/https)"),
    tenant_id: UUID = Query(..., description="ID del tenant"),
    source_by: str = Query("odin", description="Quién solicita: odin, ai-content, etc."),
    force_refresh: bool = Query(False, description="Forzar fetch sin cache"),
    task_id: str | None = Query(None, description="ID de tarea asociada (opcional)"),
):
    """
    Nivel 1: Fetch seguro de una URL.

    Protecciones:
    - SSRF: bloquea IPs privadas, metadata endpoints, file://
    - Rate limiting por tenant
    - Máximo 5MB de contenido
    - Cache por tenant+URL
    - Registro en BD con trazabilidad completa
    """
    try:
        result = await web_research_service.fetch_url(
            url=url,
            tenant_id=str(tenant_id),
            source_by=source_by,
            task_id=task_id,
            force_refresh=force_refresh,
        )
        return {"status": "success", "result": result.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Fetch failed: {e!s}") from None


@router.post("/browser")
async def api_browser_session(
    url: str = Query(..., description="URL a visitar con browser headless"),
    tenant_id: UUID = Query(..., description="ID del tenant"),
    source_by: str = Query("odin", description="Quién solicita"),
    take_screenshot: bool = Query(False, description="Capturar screenshot"),
    extract_content: bool = Query(True, description="Extraer contenido Markdown"),
    wait_for_selector: str | None = Query(None, description="Esperar selector"),
    task_id: str | None = Query(None, description="ID de tarea asociada (opcional)"),
):
    """
    Nivel 2: Browser headless con Playwright.

    Uso: páginas con JS, login flows, screenshots.
    Cada sesión está aislada (no comparte cookies entre tenants).
    """
    try:
        result = await web_research_service.browser_session(
            url=url,
            tenant_id=str(tenant_id),
            source_by=source_by,
            task_id=task_id,
            take_screenshot=take_screenshot,
            extract_content=extract_content,
            wait_for_selector=wait_for_selector,
        )
        return {"status": "success", "result": result.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Browser failed: {e!s}") from None
