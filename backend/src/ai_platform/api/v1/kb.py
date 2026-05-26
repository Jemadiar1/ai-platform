"""Knowledge Base management endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ai_platform.orchestrator.knowledge_base import Document, get_knowledge_base

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/kb", tags=["knowledge-base"])


class CreateDocumentRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/documents")
async def create_document(
    request: CreateDocumentRequest,
    tenant_id: str = Query(..., description="ID del tenant propietario"),
):
    """Agregar un documento a la base de conocimiento del tenant."""
    kb = get_knowledge_base()

    doc = Document(
        tenant_id=tenant_id,
        content=request.content,
        title=request.title,
        category=request.metadata.get("category"),
        metadata=request.metadata,
    )

    doc_id = await kb.add_document(
        tenant_id=tenant_id,
        content=request.content,
        title=request.title,
        category=request.metadata.get("category"),
        metadata=request.metadata,
    )

    return {
        "id": doc_id,
        "title": request.title,
        "content": request.content,
        "metadata": request.metadata,
    }


@router.get("/documents")
async def list_documents(
    tenant_id: str = Query(..., description="ID del tenant"),
    category: str | None = Query(None, description="Filtrar por categoría"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Listar documentos de la base de conocimiento del tenant."""
    kb = get_knowledge_base()

    raw_docs = await kb.list_documents(tenant_id=tenant_id, category=category, limit=limit + offset)
    total = len(raw_docs)
    return {
        "documents": raw_docs[offset:],
        "total": total,
    }


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    tenant_id: str = Query(..., description="ID del tenant"),
):
    """Obtener un documento específico."""
    kb = get_knowledge_base()
    doc = await kb.get_document(document_id)

    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    if doc.get("metadata", {}).get("tenant_id") != tenant_id:
        # Fallback: check cached doc tenant_id
        cached = kb._documents.get(document_id)
        if cached and cached.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Acceso denegado")

    return doc


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    tenant_id: str = Query(..., description="ID del tenant"),
):
    """Eliminar un documento de la base de conocimiento."""
    kb = get_knowledge_base()
    removed = await kb.remove_document(document_id)

    if not removed:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    return {"status": "deleted", "document_id": document_id}
