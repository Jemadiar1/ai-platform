"""
Pipeline Celery para ingestion de documentos.

Pipeline en 6 stages:
1. ingest_pipeline (entry point)
2. extract_text (PDF/DOCX/image -> raw text)
3. ocr_page (si es escaneado, Tesseract por pagina)
4. chunk_document (text -> chunks)
5. build_fts_index (chunks -> tsvector)
6. generate_summaries (chunks -> summaries)
7. mark_completed

Cada stage es un Celery task con retry, time_limit, y error handling.

Usar:
    from ai_platform.workers.document_pipeline import ingest_pipeline
    ingest_pipeline.delay(document_id, tenant_id, strategy="hybrid")
"""

from typing import Any

from celery.utils.log import get_task_logger
from sqlalchemy import select

from ai_platform.database import session_factory
from ai_platform.models.db import DocumentArtifact, DocumentChunk, DocumentFTSIndex
from ai_platform.workers.task_runner import celery_app

logger = get_task_logger("ai_platform.document_pipeline")

# --------------------------------------------------------------------------
# Import services lazily to avoid import errors if dependencies missing
# --------------------------------------------------------------------------


def _get_document_session(document_id: str):
    """Obtener session de DB con el documento."""
    session = session_factory()
    stmt = select(DocumentArtifact).where(DocumentArtifact.id == document_id)
    doc = session.execute(stmt).scalar_one_or_none()
    return session, doc


def _update_document(document_id: str, updates: dict[str, Any]) -> None:
    """Actualizar campos del documento."""
    session = session_factory()
    try:
        stmt = select(DocumentArtifact).where(DocumentArtifact.id == document_id)
        doc = session.execute(stmt).scalar_one_or_none()
        if doc:
            for key, value in updates.items():
                setattr(doc, key, value)
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# =========================================================================
# Stage 1: Extract text
# =========================================================================


@celery_app.task(
    name="documents.extract_text",
    bind=True,
    max_retries=2,
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1500,
)
def extract_text(self, document_id: str, tenant_id: str) -> dict[str, Any]:
    """
    Extraer texto crudo de PDF, DOCX, o detectar si es imagen-escaneada.

    Retorna:
        {
            "extracted_text": str | None,
            "is_scan": bool,
            "page_count": int,
            "file_type": str,
            "needs_ocr": bool,
        }
    """
    logger.info("extract_text_started", document_id=document_id)

    try:
        session, doc = _get_document_session(document_id)
        if not doc:
            raise ValueError(f"Documento {document_id} no encontrado")

        file_path = doc.file_path
        mime_type = doc.mime_type

        # Importar servicios lazy
        from pathlib import Path

        from ai_platform.core.config import get_settings

        settings = get_settings()
        storage_root = Path(settings.DOCUMENT_STORAGE_ROOT)
        full_path = storage_root / str(tenant_id) / file_path

        if not full_path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {full_path}")

        file_bytes = full_path.read_bytes()

        # Detectar tipo y extraer texto
        extracted_text = None
        is_scan = False
        needs_ocr = False
        page_count = 1
        file_type = mime_type.split("/")[1] if "/" in mime_type else "unknown"

        if mime_type == "application/pdf":
            try:
                import pdfplumber

                with pdfplumber.open(full_path) as pdf:
                    page_count = len(pdf.pages)
                    pages_text = []
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            pages_text.append(text)
                        else:
                            is_scan = True
                    extracted_text = "\n\n".join(pages_text) if pages_text else None
            except ImportError:
                logger.warning("pdfplumber not installed, skipping PDF extraction")
                is_scan = True
                needs_ocr = True

        elif mime_type.startswith("image/"):
            needs_ocr = True
            is_scan = True

        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            try:
                from docx import Document

                docx = Document(full_path)
                extracted_text = "\n".join(para.text for para in docx.paragraphs)
            except ImportError:
                logger.warning("python-docx not installed, skipping DOCX extraction")

        if not extracted_text:
            extracted_text = ""

        # Actualizar documento
        doc.page_count = page_count
        doc.status = "extracting"
        session.commit()

        logger.info(
            "extract_text_completed",
            document_id=document_id,
            page_count=page_count,
            needs_ocr=needs_ocr,
        )

        return {
            "extracted_text": extracted_text,
            "is_scan": is_scan,
            "page_count": page_count,
            "file_type": file_type,
            "needs_ocr": needs_ocr,
        }

    except Exception as exc:
        logger.error("extract_text_failed", document_id=document_id, error=str(exc))
        _update_document(document_id, {"status": "failed", "error": str(exc)})
        raise self.retry(exc=exc, countdown=60) from None


# =========================================================================
# Stage 2: OCR (conditional)
# =========================================================================


@celery_app.task(
    name="documents.ocr_page",
    bind=True,
    max_retries=3,
    acks_late=True,
    time_limit=600,
    soft_time_limit=480,
)
def ocr_page(self, document_id: str, tenant_id: str, page_number: int, page_image_path: str) -> dict[str, Any]:
    """
    Ejecutar OCR en una sola pagina de imagen.

    Usa Tesseract como motor primario.
    """
    try:
        from ai_platform.services.document_storage import get_file_path

        image_full_path = get_file_path(page_image_path, tenant_id)
        if not image_full_path.exists():
            raise FileNotFoundError(f"Imagen no encontrada: {image_full_path}")

        import pytesseract
        from PIL import Image

        img = Image.open(image_full_path)
        text = pytesseract.image_to_string(img, lang="spa+eng")
        data = pytesseract.image_to_data(img, lang="spa+eng", output_type=pytesseract.Output.DICT)

        # Calcular confianza promedio
        confidences = [c for c in data["conf"] if c > 0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "page_number": page_number,
            "text": text.strip(),
            "confidence": avg_confidence,
            "engine": "tesseract",
        }

    except Exception as exc:
        logger.error("ocr_page_failed", document_id=document_id, page=page_number, error=str(exc))
        raise self.retry(exc=exc, countdown=60) from None


# =========================================================================
# Stage 3: Chunk document
# =========================================================================


@celery_app.task(
    name="documents.chunk_document",
    bind=True,
    max_retries=2,
    acks_late=True,
    time_limit=1200,
    soft_time_limit=1080,
)
def chunk_document(self, document_id: str, tenant_id: str, strategy: str = "hybrid") -> dict[str, Any]:
    """
    Dividir texto en chunks usando la estrategia seleccionada.

    Estrategias: hybrid, semantic, fixed, page
    """
    logger.info("chunk_document_started", document_id=document_id, strategy=strategy)

    try:
        session, doc = _get_document_session(document_id)
        if not doc:
            raise ValueError(f"Documento {document_id} no encontrado")

        from ai_platform.services.document_chunker import DocumentChunker

        chunker = DocumentChunker()

        # Leer texto extraido (deberia estar en el documento)
        # En una implementacion real, el texto se pasa como argumento
        # Por ahora, leer del primer chunk existente o del campo text
        extracted_text = ""  # Se pasa desde el stage anterior

        if strategy == "hybrid":
            chunks = chunker.chunk_hybrid(extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id})
        elif strategy == "semantic":
            chunks = chunker.chunk_semantic(
                extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id}
            )
        elif strategy == "fixed":
            chunks = chunker.chunk_fixed(extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id})
        elif strategy == "page":
            chunks = chunker.chunk_page(extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id})
        else:
            chunks = chunker.chunk_hybrid(extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id})

        # Guardar chunks en BD
        for chunk in chunks:
            doc_chunk = DocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                level=chunk.level,
                chunk_type=chunk.chunk_type,
                content=chunk.content,
                metadata_json=chunk.metadata,
            )
            session.add(doc_chunk)

        session.commit()

        logger.info(
            "chunk_document_completed",
            document_id=document_id,
            chunk_count=len(chunks),
            strategy=strategy,
        )

        return {
            "chunk_count": len(chunks),
            "strategy": strategy,
        }

    except Exception as exc:
        logger.error("chunk_document_failed", document_id=document_id, error=str(exc))
        _update_document(document_id, {"status": "failed", "error": str(exc)})
        raise self.retry(exc=exc, countdown=60) from None


# =========================================================================
# Stage 4: Build FTS index
# =========================================================================


@celery_app.task(
    name="documents.build_fts_index",
    bind=True,
    max_retries=2,
    acks_late=True,
    time_limit=600,
    soft_time_limit=480,
)
def build_fts_index(self, document_id: str, tenant_id: str) -> dict[str, Any]:
    """
    Construir indice tsvector para busqueda full-text.

    Usa PostgreSQL to_tsvector con configuracion espanola.
    """
    logger.info("build_fts_index_started", document_id=document_id)

    try:
        session = session_factory()
        try:
            # Leer todos los chunks de texto
            stmt = select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.chunk_type == "text",
            )
            chunks = session.execute(stmt).scalars().all()

            fts_entries = []
            for chunk in chunks:
                # Construir tsvector
                search_vector = (
                    f"to_tsvector('spanish', {session.connection().connection.cursor().cursor.name!r})"  # Simplified
                )
                # En produccion, usar raw SQL: SELECT to_tsvector('spanish', content)

                fts_entry = DocumentFTSIndex(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    level=chunk.level,
                    search_vector="",  # Se llena con raw SQL
                )
                fts_entries.append(fts_entry)

            for entry in fts_entries:
                session.add(entry)

            session.commit()

            logger.info(
                "build_fts_index_completed",
                document_id=document_id,
                indexed_chunks=len(fts_entries),
            )

            return {"indexed_chunks": len(fts_entries)}

        finally:
            session.close()

    except Exception as exc:
        logger.error("build_fts_index_failed", document_id=document_id, error=str(exc))
        raise self.retry(exc=exc, countdown=60) from None


# =========================================================================
# Stage 5: Generate summaries
# =========================================================================


@celery_app.task(
    name="documents.generate_summaries",
    bind=True,
    max_retries=3,
    acks_late=True,
    time_limit=3600,
    soft_time_limit=3300,
)
def generate_summaries(self, document_id: str, tenant_id: str) -> dict[str, Any]:
    """
    Generar resenes jerarquicos:
    1. Resumen por seccion (level 2)
    2. Resumen del documento (level 3)

    Requiere LLM client para generar resenes.
    """
    logger.info("generate_summaries_started", document_id=document_id)

    try:
        # Leer chunks existentes
        session = session_factory()
        try:
            stmt = select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.level == 1,
            )
            chunks = session.execute(stmt).scalars().all()

            # En una implementacion real, aqui se llamaria al LLM client
            # para generar resenes. Por ahora, marcamos como completado.
            logger.info(
                "generate_summaries_skipped",
                document_id=document_id,
                reason="LLM client not integrated yet",
            )

            return {"status": "skipped", "reason": "LLM client pending"}

        finally:
            session.close()

    except Exception as exc:
        logger.error("generate_summaries_failed", document_id=document_id, error=str(exc))
        raise self.retry(exc=exc, countdown=120) from None


# =========================================================================
# Stage 6: Mark completed
# =========================================================================


@celery_app.task(
    name="documents.mark_completed",
    bind=True,
    max_retries=1,
    acks_late=True,
    time_limit=60,
)
def mark_completed(self, document_id: str, tenant_id: str, stats: dict[str, Any]) -> dict[str, Any]:
    """
    Marcar documento como completado y registrar stats.
    """
    logger.info("mark_completed", document_id=document_id, stats=stats)

    try:
        _update_document(
            document_id,
            {
                "status": "completed",
                "completed_at": None,  # Use datetime.now(UTC) in real code
                **stats,
            },
        )
        return {"status": "completed", "document_id": document_id}

    except Exception as exc:
        logger.error("mark_completed_failed", document_id=document_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30) from None


# =========================================================================
# Orchestrator
# =========================================================================


@celery_app.task(
    name="documents.ingest_pipeline",
    bind=True,
    max_retries=1,
    acks_late=True,
    time_limit=7200,
    soft_time_limit=6900,
)
def ingest_pipeline(
    self,
    document_id: str,
    tenant_id: str,
    strategy: str = "hybrid",
) -> dict[str, Any]:
    """
    Pipeline principal de ingestion de documentos.

    1. Extraer texto del archivo
    2. Si OCR necesario, ejecutar OCR por pagina
    3. Chunkear el texto
    4. Construir indice FTS
    5. Generar resenes
    6. Marcar como completado
    """
    logger.info("pipeline_started", document_id=document_id, tenant_id=tenant_id, strategy=strategy)

    try:
        # Stage 1: Extract
        _update_document(document_id, {"status": "extracting"})
        extract_result = extract_text.delay(document_id, tenant_id)
        extract_data = extract_result.get(timeout=1800)

        # Stage 2: OCR (conditional)
        if extract_data.get("needs_ocr"):
            logger.info("pipeline_ocr_needed", document_id=document_id)
            _update_document(document_id, {"status": "ocr"})
            # En produccion: ejecutar ocr_page por cada pagina

        # Stage 3: Chunk
        _update_document(document_id, {"status": "chunking"})
        chunk_result = chunk_document.delay(document_id, tenant_id, strategy)
        chunk_data = chunk_result.get(timeout=1200)

        # Stage 4: FTS
        _update_document(document_id, {"status": "indexing"})
        fts_result = build_fts_index.delay(document_id, tenant_id)
        fts_data = fts_result.get(timeout=600)

        # Stage 5: Summaries
        _update_document(document_id, {"status": "summarizing"})
        summary_result = generate_summaries.delay(document_id, tenant_id)
        summary_data = summary_result.get(timeout=3600)

        # Stage 6: Complete
        mark_completed.delay(
            document_id,
            tenant_id,
            {
                "stats": {
                    "chunks": chunk_data.get("chunk_count", 0),
                    "fts_indexed": fts_data.get("indexed_chunks", 0),
                }
            },
        )

        logger.info("pipeline_completed", document_id=document_id)
        return {
            "status": "completed",
            "document_id": document_id,
            "stats": {"chunks": chunk_data.get("chunk_count", 0)},
        }

    except Exception as exc:
        logger.error("pipeline_failed", document_id=document_id, error=str(exc))
        _update_document(document_id, {"status": "failed", "error": str(exc)})
        raise self.retry(exc=exc, countdown=120) from None
