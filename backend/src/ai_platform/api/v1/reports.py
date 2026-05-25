"""
API de generación de reportes profesionales.

Endpoints:
- POST /reports/generate - Genera reporte desde ReportSpec JSON
- GET /reports - Lista reportes del tenant
- GET /reports/{id} - Metadata del reporte
- GET /reports/{id}/download/{format} - Descarga en formato específico

No es un módulo vendible: es infraestructura interna para report_renderer.
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


@router.post("/generate")
async def generate_report(
    report_spec: dict,
    formats: list[str] = Query(["html", "pdf"], description="Formatos: html, pdf, docx, xlsx, csv"),
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
):
    """
    Generar un reporte profesional desde ReportSpec JSON.

    El ReportSpec debe incluir:
    - title: str
    - audience: str
    - sections: list[{id, title, content, charts?, tables?}]
    - theme: {primary_color, secondary_color, font_family, company_name}

    Retorna report_id y formatos disponibles.
    """
    from ai_platform.services.report_models import (
        BrandTheme,
        ChartSpec,
        ChartType,
        Citation,
        ReportSpec,
        Section,
        TableSpec,
    )
    from ai_platform.services.report_renderer import ReportRendererService

    # Construir ReportSpec desde dict
    try:
        sections = []
        for s in report_spec.get("sections", []):
            charts = [
                ChartSpec(
                    id=c["id"],
                    title=c["title"],
                    type=ChartType(c["type"]),
                    data=c["data"],
                    colors=c.get("colors"),
                )
                for c in s.get("charts", [])
            ]
            tables = [
                TableSpec(
                    id=t["id"],
                    title=t["title"],
                    headers=t["headers"],
                    rows=t["rows"],
                )
                for t in s.get("tables", [])
            ]
            citations = [
                Citation(text=c["text"], source=c["source"], url=c.get("url"))
                for c in s.get("citations", [])
            ]
            sections.append(
                Section(
                    id=s["id"],
                    title=s["title"],
                    content=s["content"],
                    charts=charts,
                    tables=tables,
                    citations=citations,
                )
            )

        theme_data = report_spec.get("theme", {})
        theme = BrandTheme(
            primary_color=theme_data.get("primary_color", "#1a73e8"),
            secondary_color=theme_data.get("secondary_color", "#5f6368"),
            font_family=theme_data.get("font_family", "Arial, sans-serif"),
            company_name=theme_data.get("company_name", "NeuralCrew Labs"),
        )

        report_spec_obj = ReportSpec(
            title=report_spec["title"],
            audience=report_spec.get("audience", ""),
            sections=sections,
            theme=theme,
            generated_by=report_spec.get("generated_by", "api"),
            version=report_spec.get("version", "1.0"),
        )

        # Renderizar
        renderer = ReportRendererService()
        format_enums = []
        for f in formats:
            if f == "html":
                from ai_platform.services.report_models import ReportFormat

                format_enums.append(ReportFormat.HTML)
            elif f == "pdf":
                format_enums.append(ReportFormat.PDF)
            elif f == "docx":
                format_enums.append(ReportFormat.DOCX)
            elif f == "xlsx":
                format_enums.append(ReportFormat.XLSX)
            elif f == "csv":
                format_enums.append(ReportFormat.CSV)

        outputs = renderer.render(tenant_id, report_spec_obj, format_enums)

        return {
            "status": "success",
            "formats_available": list(outputs.keys()),
            "file_sizes": {k: len(v) for k, v in outputs.items()},
        }

    except Exception as e:
        logger.error(f"report_generation_failed: {e}")
        raise HTTPException(status_code=500, detail=f"Error generando reporte: {e}") from None


@router.get("")
def list_reports(
    tenant_id: str = Query(..., description="ID del tenant"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    """Listar reportes del tenant con paginación."""
    stmt = (
        select(GeneratedReport)
        .where(GeneratedReport.tenant_id == UUID(tenant_id))
        .order_by(GeneratedReport.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    reports = db.execute(stmt).scalars().all()

    return {
        "reports": [
            {
                "id": str(r.id),
                "title": r.title,
                "audience": r.audience,
                "formats": r.generated_formats,
                "file_size_bytes": r.file_size_bytes,
                "rendering_time_ms": r.rendering_time_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{report_id}")
def get_report(
    report_id: UUID,
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
):
    """Metadata de un reporte."""
    stmt = select(GeneratedReport).where(
        GeneratedReport.id == report_id,
        GeneratedReport.tenant_id == UUID(tenant_id),
    )
    report = db.execute(stmt).scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    return {
        "id": str(report.id),
        "title": report.title,
        "audience": report.audience,
        "formats": report.generated_formats,
        "file_size_bytes": report.file_size_bytes,
        "rendering_time_ms": report.rendering_time_ms,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/{report_id}/download/{format}")
def download_report(
    report_id: UUID,
    format: str = Query(..., description="Formato: html, pdf, docx, xlsx, csv"),
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
):
    """Descargar reporte en formato específico."""
    stmt = select(GeneratedReport).where(
        GeneratedReport.id == report_id,
        GeneratedReport.tenant_id == UUID(tenant_id),
    )
    report = db.execute(stmt).scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    if format not in report.generated_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Formato {format} no disponible. Formatos: {report.generated_formats}",
        )

    # Mapear formato a campo
    field_map = {
        "html": report.html_content,
        "pdf": report.pdf_blob,
        "docx": report.docx_blob,
        "xlsx": report.xlsx_blob,
        "csv": report.csv_content,
    }

    content = field_map.get(format)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Contenido {format} no disponible")

    # Determinar media type
    media_types = {
        "html": "text/html",
        "pdf": "application/pdf",
        "docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
    }

    filename_map = {
        "html": f"{report.title}.html",
        "pdf": f"{report.title}.pdf",
        "docx": f"{report.title}.docx",
        "xlsx": f"{report.title}.xlsx",
        "csv": f"{report.title}.csv",
    }

    # Si es string (html/csv), convertir a bytes
    if isinstance(content, str):
        content = content.encode("utf-8")

    return StreamingResponse(
        BytesIO(content),
        media_type=media_types.get(format, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{filename_map.get(format, "report")}"'
        },
    )
