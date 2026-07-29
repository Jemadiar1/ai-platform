"""
API de generación de documentos profesionales (ai-documents).

Endpoints:
- POST /ai_documents/generate_docx - Genera DOCX desde markdown/contenido
- POST /ai_documents/generate_xlsx - Genera XLSX desde markdown/contenido
- POST /ai_documents/generate_pptx - Genera PPTX desde markdown/contenido
- POST /ai_documents/generate_png  - Genera imagen PNG
- POST /ai_documents/generate_pdf  - Genera PDF desde markdown/contenido
- POST /ai_documents/generate_all  - Genera todos los formatos
- GET  /ai_documents              - Lista documentos generados

"""

import logging
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_platform.database import get_db_session
from ai_platform.models.db import GeneratedReport

logger = logging.getLogger(__name__)

router = APIRouter()


def _tenant_id_from_query(tenant_id: str | None = Query(None, description="ID del tenant"),
                          db: Session = None) -> str:
    """Obtener tenant_id desde query parameter o from current tenant."""
    if tenant_id:
        return tenant_id
    # Fallback: could use auth middleware tenant
    raise HTTPException(status_code=400, detail="tenant_id query parameter is required")


# =========================================================================
# Generation endpoints
# =========================================================================


@router.post("/generate_docx", summary="Generar documento DOCX")
def generate_docx(
    body: dict,
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
) -> dict:
    """
    Generar un documento DOCX profesional a partir de contenido markdown.

    Body JSON esperado:
    ```json
    {
        "subject": "Reporte de Ventas Q3",
        "content": "# Reporte Q3\\n## Resumen\\nLas ventas aumentaron 15%...",
        "audience": "Director Comercial",
        "theme": {"primary_color": "#1a73e8", "company_name": "MiEmpresa"}
    }
    ```

    Parámetros de gráfico (opcional en body):
    ```json
    {
        "chart_specs": [
            {
                "id": "chart1",
                "type": "bar",
                "title": "Ventas Mensuales",
                "data": [{"label": "Ene", "value": 1500}, {"label": "Feb", "value": 2100}],
                "colors": ["#1a73e8", "#e84393"]
            }
        ]
    }
    ```
    """
    from ai_platform.modules.ai_documents.generators import Generators

    params = body.copy()
    # Mover chart_specs si están presentes para que generador los procese
    if "chart_specs" in params:
        params["charts"] = params.pop("chart_specs")

    g = Generators(tenant_id)
    result = g.render_docx(tenant_id, params)

    if not result.get("docx"):
        raise HTTPException(status_code=500, detail="Error generando documento DOCX")

    return {
        "status": "success",
        "format": result["format"],
        "filename": result["filename"],
        "file_size_bytes": result["file_size_bytes"],
        "rendering_ms": result["rendering_ms"],
    }


@router.post("/generate_xlsx", summary="Generar hoja de cálculo XLSX")
def generate_xlsx(
    body: dict,
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
) -> dict:
    """Generar XLSX profesional desde contenido markdown."""
    from ai_platform.modules.ai_documents.generators import Generators

    params = body.copy()
    if "chart_specs" in params:
        params["charts"] = params.pop("chart_specs")

    g = Generators(tenant_id)
    result = g.render_xlsx(tenant_id, params)

    if not result.get("xlsx"):
        raise HTTPException(status_code=500, detail="Error generando hoja XLSX")

    return {
        "status": "success",
        "format": result["format"],
        "filename": result["filename"],
        "file_size_bytes": result["file_size_bytes"],
        "rendering_ms": result["rendering_ms"],
    }


@router.post("/generate_pptx", summary="Generar presentación PPTX")
def generate_pptx(
    body: dict,
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
) -> dict:
    """Generar presentación PPTX profesional desde contenido markdown."""
    from ai_platform.modules.ai_documents.generators import Generators

    params = body.copy()
    if "chart_specs" in params:
        params["charts"] = params.pop("chart_specs")

    g = Generators(tenant_id)
    result = g.render_pptx(tenant_id, params)

    if not result.get("pptx"):
        raise HTTPException(status_code=500, detail="Error generando presentación PPTX")

    return {
        "status": "success",
        "format": result["format"],
        "filename": result["filename"],
        "file_size_bytes": result["file_size_bytes"],
        "rendering_ms": result["rendering_ms"],
    }


@router.post("/generate_png", summary="Generar imagen PNG")
def generate_png(
    body: dict,
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
) -> dict:
    """Generar imagen PNG (gráfico, banner, infografía) usando Pillow."""
    from ai_platform.modules.ai_documents.generators import Generators

    params = body.copy()

    g = Generators(tenant_id)
    result = g.render_png(tenant_id, params)

    if not result.get("png"):
        raise HTTPException(status_code=500, detail="Error generando imagen PNG")

    return {
        "status": "success",
        "format": result["format"],
        "filename": result["filename"],
        "file_size_bytes": result["file_size_bytes"],
        "rendering_ms": result["rendering_ms"],
        "data_uri": result.get("data_uri"),
    }


@router.post("/generate_pdf", summary="Generar documento PDF")
def generate_pdf(
    body: dict,
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
) -> dict:
    """Generar PDF profesional desde contenido markdown (WeasyPrint o report_renderer)."""
    from ai_platform.modules.ai_documents.generators import Generators

    params = body.copy()
    if "chart_specs" in params:
        params["charts"] = params.pop("chart_specs")

    g = Generators(tenant_id)
    result = g.render_pdf(tenant_id, params)

    if not result.get("pdf"):
        raise HTTPException(status_code=500, detail="Error generando PDF")

    return {
        "status": "success",
        "format": result["format"],
        "filename": result["filename"],
        "file_size_bytes": result["file_size_bytes"],
        "rendering_ms": result["rendering_ms"],
    }


@router.post("/generate_all", summary="Generar todos los formatos")
def generate_all(
    body: dict,
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
) -> dict:
    """Generar todos los formatos disponibles (DOCX, XLSX, PPTX, PDF, PNG)."""
    from ai_platform.modules.ai_documents.generators import Generators

    params = body.copy()
    if "chart_specs" in params:
        params["charts"] = params.pop("chart_specs")

    g = Generators(tenant_id)
    result = g.render_all(tenant_id, params)

    return result


# =========================================================================
# Download / list endpoints
# =========================================================================


@router.get("/{report_id}/download/{format}")
def download_ai_document(
    report_id: UUID,
    format: str,
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
) -> StreamingResponse:
    """Descargar documento generado en formato específico."""
    stmt = select(GeneratedReport).where(
        GeneratedReport.id == report_id,
        GeneratedReport.tenant_id == UUID(tenant_id),
    )
    report = db.execute(stmt).scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    if "pdf" in report.generated_formats and format == "pdf" and report.pdf_blob:
        return StreamingResponse(
            BytesIO(report.pdf_blob),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{report.title}.pdf"'},
        )
    if "docx" in report.generated_formats and format == "docx" and report.docx_blob:
        return StreamingResponse(
            BytesIO(report.docx_blob),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{report.title}.docx"'},
        )
    if "xlsx" in report.generated_formats and format == "xlsx" and report.xlsx_blob:
        return StreamingResponse(
            BytesIO(report.xlsx_blob),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{report.title}.xlsx"'},
        )
    if "html" in report.generated_formats and format == "html" and report.html_content:
        return StreamingResponse(
            BytesIO(report.html_content.encode("utf-8")),
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{report.title}.html"'},
        )

    raise HTTPException(status_code=400, detail=f"Formato '{format}' no disponible para este documento")


@router.get("")
def list_generated_documents(
    tenant_id: str = Query(..., description="ID del tenant"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
) -> dict:
    """Listar documentos generados por el tenant (DOCX, PPTX, XLSX, PDF, PNG)."""
    stmt = (
        select(GeneratedReport)
        .where(GeneratedReport.tenant_id == UUID(tenant_id))
        .order_by(GeneratedReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    reports = db.execute(stmt).scalars().all()

    return {
        "documents": [
            {
                "id": str(r.id),
                "title": r.title,
                "audience": r.audience,
                "formats": r.generated_formats,
                "file_size_bytes": r.file_size_bytes,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
        "limit": limit,
        "offset": offset,
    }