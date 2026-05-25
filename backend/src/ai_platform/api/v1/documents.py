"""
API de documentos para ingestión asíncrona.

Endpoints:
- POST /documents/upload - Sube archivo, dispara pipeline Celery
- GET /documents - Lista documentos del tenant
- GET /documents/{id} - Metadata y status
- GET /documents/{id}/chunks - Lista chunks
- GET /documents/{id}/search - Búsqueda FTS
- GET /documents/search - Búsqueda global

No es un módulo vendible: es infraestructura interna para document_ingestion.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_platform.core.config import get_settings
from ai_platform.database import get_db_session
from ai_platform.models.db import DocumentArtifact, DocumentChunk

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()

# Formatos aceptados
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "image/bmp",
}

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

# Tamaño máximo: 100MB
MAX_UPLOAD_SIZE = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


def _validate_filename(filename: str) -> bool:
    """Validar extensión del archivo."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ALLOWED_EXTENSIONS


def _validate_mime_type(content_type: str | None) -> bool:
    """Validar tipo MIME del archivo."""
    if not content_type:
        return False
    # Manejar content-type con charset: "application/pdf; charset=utf-8"
    base_type = content_type.split(";")[0].strip()
    return base_type in ALLOWED_MIME_TYPES


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(..., description="Archivo a subir (PDF, DOCX, PNG, JPG, TIFF)"),
    strategy: str = Query("hybrid", description="Estrategia de chunking: hybrid, semantic, fixed, page"),
    db: Session = Depends(get_db_session),
):
    """
    Subir un documento para procesamiento asíncrono.

    El archivo se guarda inmediatamente y el pipeline Celery
    comienza a procesarlo en background.

    Retorna document_id inmediatamente.
    """
    # Validar nombre
    if not _validate_filename(file.filename or ""):
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado. Formatos aceptados: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Validar MIME type
    if not _validate_mime_type(file.content_type):
        raise HTTPException(
            status_code=400,
            detail=f"Tipo MIME no soportado: {file.content_type}",
        )

    # Leer contenido
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo demasiado grande. Máximo: {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    # Crear registro
    from ai_platform.services.document_storage import save_uploaded_file

    file_name = save_uploaded_file(content, file.filename, "current-tenant")  # tenant_id se inyecta via middleware

    doc = DocumentArtifact(
        tenant_id=UUID("00000000-0000-0000-0000-000000000000"),  # Se sobrescribe con tenant real
        name=file.filename or "unknown",
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        file_path=file_name,
        storage_backend="local",
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Disparar pipeline Celery
    from ai_platform.workers.document_pipeline import ingest_pipeline

    ingest_pipeline.delay(str(doc.id), str(doc.tenant_id), strategy)

    logger.info("document_uploaded", document_id=str(doc.id), filename=file.filename)

    return {
        "status": "uploaded",
        "document_id": str(doc.id),
        "filename": file.filename,
        "size_bytes": len(content),
        "status_url": f"/api/v1/documents/{doc.id}",
    }


@router.get("")
def list_documents(
    tenant_id: str = Query(..., description="ID del tenant"),
    status_filter: str | None = Query(None, description="Filtrar por status: pending, processing, completed, failed"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    """Listar documentos del tenant con paginación."""
    stmt = (
        select(DocumentArtifact)
        .where(DocumentArtifact.tenant_id == UUID(tenant_id))
        .order_by(DocumentArtifact.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if status_filter:
        stmt = stmt.where(DocumentArtifact.status == status_filter)

    docs = db.execute(stmt).scalars().all()

    return {
        "documents": [
            {
                "id": str(d.id),
                "name": d.name,
                "mime_type": d.mime_type,
                "size_bytes": d.size_bytes,
                "status": d.status,
                "page_count": d.page_count,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{document_id}")
def get_document(
    document_id: UUID,
    tenant_id: str = Query(..., description="ID del tenant"),
    db: Session = Depends(get_db_session),
):
    """Metadata y status de un documento."""
    stmt = select(DocumentArtifact).where(
        DocumentArtifact.id == document_id,
        DocumentArtifact.tenant_id == UUID(tenant_id),
    )
    doc = db.execute(stmt).scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    # Contar chunks
    chunk_stmt = select(DocumentChunk).where(
        DocumentChunk.document_id == document_id,
        DocumentChunk.tenant_id == UUID(tenant_id),
    )
    chunk_count = len(db.execute(chunk_stmt).scalars().all())

    return {
        "id": str(doc.id),
        "name": doc.name,
        "mime_type": doc.mime_type,
        "size_bytes": doc.size_bytes,
        "status": doc.status,
        "page_count": doc.page_count,
        "chunk_count": chunk_count,
        "error": doc.error,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "completed_at": doc.completed_at.isoformat() if doc.completed_at else None,
    }


@router.get("/{document_id}/chunks")
def list_chunks(
    document_id: UUID,
    tenant_id: str = Query(..., description="ID del tenant"),
    level: int | None = Query(None, description="Filtrar por nivel: 1=text, 2=section summary, 3=document summary"),
    chunk_type: str | None = Query(None, description="Filtrar por tipo: text, summary_section, summary_document"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
):
    """Listar chunks de un documento con paginación."""
    stmt = (
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.tenant_id == UUID(tenant_id),
        )
        .order_by(DocumentChunk.chunk_index)
        .limit(limit)
        .offset(offset)
    )

    if level is not None:
        stmt = stmt.where(DocumentChunk.level == level)
    if chunk_type:
        stmt = stmt.where(DocumentChunk.chunk_type == chunk_type)

    chunks = db.execute(stmt).scalars().all()

    return {
        "chunks": [
            {
                "id": str(c.id),
                "chunk_index": c.chunk_index,
                "level": c.level,
                "chunk_type": c.chunk_type,
                "content_preview": c.content[:200] + "..." if len(c.content) > 200 else c.content,
                "content_length": len(c.content),
                "metadata": c.metadata_json,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in chunks
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{document_id}/search")
def search_document(
    document_id: UUID,
    tenant_id: str = Query(..., description="ID del tenant"),
    q: str = Query(..., min_length=1, description="Query de búsqueda"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db_session),
):
    """Búsqueda full-text dentro de un documento."""
    # Usar PostgreSQL tsvector para búsqueda
    from sqlalchemy import text

    stmt = text(
        """
        SELECT dc.id, dc.content, dc.chunk_index, dc.level, dc.chunk_type, dc.metadata_json
        FROM document_chunks dc
        WHERE dc.document_id = :document_id
          AND dc.tenant_id = :tenant_id
          AND dc.chunk_type = 'text'
          AND to_tsvector('spanish', dc.content) @@ plainto_tsquery('spanish', :query)
        ORDER BY ts_rank(to_tsvector('spanish', dc.content), plainto_tsquery('spanish', :query)) DESC
        LIMIT :limit
        """
    )

    result = db.execute(
        stmt,
        {
            "document_id": document_id,
            "tenant_id": UUID(tenant_id),
            "query": q,
            "limit": limit,
        },
    )
    rows = result.fetchall()

    return {
        "results": [
            {
                "chunk_id": str(r[0]),
                "content": r[1],
                "chunk_index": r[2],
                "level": r[3],
                "content_preview": r[1][:200] + "..." if len(r[1]) > 200 else r[1],
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.get("/search")
def search_all_documents(
    tenant_id: str = Query(..., description="ID del tenant"),
    q: str = Query(..., min_length=1, description="Query de búsqueda"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db_session),
):
    """Búsqueda full-text en todos los documentos del tenant."""
    from sqlalchemy import text

    stmt = text(
        """
        SELECT da.id, da.name, da.status, dc.content, dc.chunk_index, dc.level
        FROM document_chunks dc
        JOIN document_artifacts da ON dc.document_id = da.id
        WHERE dc.tenant_id = :tenant_id
          AND dc.chunk_type = 'text'
          AND to_tsvector('spanish', dc.content) @@ plainto_tsquery('spanish', :query)
        ORDER BY ts_rank(to_tsvector('spanish', dc.content), plainto_tsquery('spanish', :query)) DESC
        LIMIT :limit
        """
    )

    result = db.execute(
        stmt,
        {"tenant_id": UUID(tenant_id), "query": q, "limit": limit},
    )
    rows = result.fetchall()

    return {
        "results": [
            {
                "document_id": str(r[0]),
                "document_name": r[1],
                "document_status": r[2],
                "content_preview": r[3][:200] + "..." if len(r[3]) > 200 else r[3],
                "chunk_index": r[4],
            }
            for r in rows
        ],
        "total": len(rows),
    }
