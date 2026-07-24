"""
Pipeline Celery para ingestion de documentos.

Pipeline en 6 stages:
1. ingest_pipeline (entry point)
2. extract_text (PDF/DOCX/XLSX/image -> raw text)
3. ocr_all_pages (si es escaneado, Tesseract por pagina)
4. chunk_document (text -> chunks, lee de la BD)
5. build_fts_index (chunks -> tsvector)
6. generate_summaries (chunks -> summaries via LLM)
7. mark_completed

Usar:
    from ai_platform.workers.document_pipeline import ingest_pipeline
    ingest_pipeline.delay(document_id, tenant_id, strategy="hybrid")
"""

from celery.utils.log import get_task_logger
from sqlalchemy import select, text as sa_text

from ai_platform.database import session_factory
from ai_platform.models.db import DocumentArtifact, DocumentChunk, DocumentFTSIndex
from ai_platform.workers.task_runner import celery_app

logger = get_task_logger("ai_platform.document_pipeline")


def _get_document_session(document_id: str):
    """Obtener session de DB con el documento."""
    session = session_factory()
    stmt = select(DocumentArtifact).where(DocumentArtifact.id == document_id)
    doc = session.execute(stmt).scalar_one_or_none()
    return session, doc


def _update_document(document_id: str, updates: dict) -> None:
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


@celery_app.task(
    name="documents.extract_text",
    bind=True,
    max_retries=2,
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1500,
)
def extract_text(self, document_id: str, tenant_id: str) -> dict:
    """
    Extraer texto crudo de PDF, DOCX, XLSX, o imÃ¡genes.
    Guarda el texto en la BD (campo extracted_text) para que chunk_document lo lea.
    """
    logger.info("extract_text_started", document_id=document_id)
    session, doc = _get_document_session(document_id)
    if not doc:
        raise ValueError(f"Documento {document_id} no encontrado")

    file_path = doc.file_path
    mime_type = doc.mime_type

    from pathlib import Path

    from ai_platform.core.config import get_settings

    settings = get_settings()
    storage_root = Path(settings.DOCUMENT_STORAGE_ROOT)
    full_path = storage_root / str(tenant_id) / file_path

    if not full_path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {full_path}")

    file_bytes = full_path.read_bytes()

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
                        needs_ocr = True
                extracted_text = "\n\n".join(pages_text) if pages_text else None
        except ImportError:
            logger.warning("pdfplumber not installed, marking as scan")
            is_scan = True
            needs_ocr = True

    elif mime_type.startswith("image/"):
        needs_ocr = True
        is_scan = True
        extracted_text = ""

    elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            from docx import Document

            docx_obj = Document(full_path)
            extracted_text = "\n".join(para.text for para in docx_obj.paragraphs)
        except ImportError:
            logger.warning("python-docx not installed, skipping DOCX extraction")

    elif (
        mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        or "ms-excel" in mime_type
    ):
        try:
            import openpyxl

            wb = openpyxl.load_workbook(full_path, read_only=True, data_only=True)
            sheet_text = []
            for ws in wb.worksheets:
                sheet_text.append(f"--- Sheet: {ws.title} ---")
                for row in ws.iter_rows(values_only=True):
                    row_str = " | ".join(str(cell) if cell is not None else "" for cell in row)
                    if row_str.strip():
                        sheet_text.append(row_str)
                wb.close()
            extracted_text = "\n".join(sheet_text)
        except ImportError:
            logger.warning("openpyxl not installed, skipping XLSX extraction")

    elif mime_type == "text/plain":
        try:
            extracted_text = full_path.read_text(encoding="utf-8")
        except Exception:
            try:
                extracted_text = full_path.read_text(encoding="latin-1")
            except Exception:
                pass

    elif mime_type == "text/csv":
        try:
            content = full_path.read_text(encoding="utf-8")
            extracted_text = "CSV:\n" + content
        except Exception:
            pass

    if not extracted_text:
        extracted_text = ""
        if mime_type.startswith("image/"):
            needs_ocr = True
            is_scan = True

    # Guardar texto extraido en la BD
    doc.extracted_text = extracted_text
    doc.page_count = page_count
    doc.status = "extracted"
    session.commit()

    logger.info(
        "extract_text_completed",
        document_id=document_id,
        page_count=page_count,
        needs_ocr=needs_ocr,
        text_length=len(extracted_text or ""),
    )

    return {
        "extracted_text": extracted_text,
        "is_scan": is_scan,
        "page_count": page_count,
        "file_type": file_type,
        "needs_ocr": needs_ocr,
    }


@celery_app.task(
    name="documents.ocr_all_pages",
    bind=True,
    max_retries=2,
    acks_late=True,
)
def ocr_all_pages(self, document_id: str, tenant_id: str, _page_count: int = 1) -> dict:
    """
    OCR para PDFs escaneados o imÃ¡genes.
    Usa Tesseract para extraer texto de cada pÃ¡gina.
    """
    logger.info("ocr_all_pages_started", document_id=document_id)
    session, doc = _get_document_session(document_id)
    try:
        from pathlib import Path

        from ai_platform.core.config import get_settings

        settings = get_settings()
        storage_root = Path(settings.DOCUMENT_STORAGE_ROOT)
        full_path = storage_root / str(tenant_id) / doc.file_path

        if not full_path.exists():
            return {"pages_ocrd": 0}

        extracted_text_from_ocr = ""

        if doc.mime_type == "application/pdf":
            try:
                from pdf2image import convert_from_path

                images = convert_from_path(str(full_path), dpi=300)
                for img in images:
                    import pytesseract

                    page_text = pytesseract.image_to_string(img, lang="spa+eng")
                    extracted_text_from_ocr += page_text + "\n\n"
            except ImportError:
                logger.warning("pdf2image not installed, skipping PDF OCR")
        elif doc.mime_type.startswith("image/"):
            try:
                from PIL import Image

                import pytesseract

                img = Image.open(full_path)
                page_text = pytesseract.image_to_string(img, lang="spa+eng")
                extracted_text_from_ocr += page_text
            except ImportError:
                logger.warning("tesseract/PIL not installed, skipping OCR")

        if extracted_text_from_ocr:
            doc.extracted_text = (doc.extracted_text or "") + extracted_text_from_ocr
            session.commit()
            logger.info("ocr_all_pages_done", document_id=document_id, ocr_length=len(extracted_text_from_ocr))
        else:
            logger.warning("ocr_all_pages_no_text", document_id=document_id)

        return {"pages_ocrd": 1, "merged_text": extracted_text_from_ocr}
    except Exception as exc:
        logger.error("ocr_all_pages_failed", document_id=document_id, error=str(exc))
        return {"pages_ocrd": 0, "error": str(exc)}


@celery_app.task(
    name="documents.chunk_document",
    bind=True,
    max_retries=2,
    acks_late=True,
    time_limit=1200,
    soft_time_limit=1080,
)
def chunk_document(self, document_id: str, tenant_id: str, strategy: str = "hybrid") -> dict:
    """
    Dividir texto en chunks. Lee el texto desde la BD (campo extracted_text
    escrito por el stage extract_text).
    """
    logger.info("chunk_document_started", document_id=document_id, strategy=strategy)

    session, doc = _get_document_session(document_id)
    if not doc:
        raise ValueError(f"Documento {document_id} no encontrado")

    from ai_platform.services.document_chunker import DocumentChunker

    chunker = DocumentChunker()

    # Leer texto extraido desde la BD
    extracted_text = doc.extracted_text or ""
    if not extracted_text:
        logger.warning(
            "chunk_document_no_text",
            document_id=document_id,
            status=doc.status,
        )
        return {"chunk_count": 0, "strategy": strategy, "warning": "no_text_extracted"}

    if strategy == "hybrid":
        chunks = chunker.chunk_hybrid(
            extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id}
        )
    elif strategy == "semantic":
        chunks = chunker.chunk_semantic(
            extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id}
        )
    elif strategy == "fixed":
        chunks = chunker.chunk_fixed(
            extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id}
        )
    elif strategy == "page":
        chunks = chunker.chunk_page(
            extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id}
        )
    else:
        chunks = chunker.chunk_hybrid(
            extracted_text, metadata={"document_id": document_id, "tenant_id": tenant_id}
        )

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
        text_length=len(extracted_text),
    )

    return {
        "chunk_count": len(chunks),
        "strategy": strategy,
    }


@celery_app.task(
    name="documents.build_fts_index",
    bind=True,
    max_retries=2,
    acks_late=True,
    time_limit=600,
    soft_time_limit=480,
)
def build_fts_index(self, document_id: str, tenant_id: str) -> dict:
    """
    Construir indice tsvector para busqueda full-text.
    Usa PostgreSQL to_tsvector con configuracion espanola.
    Se basa en los chunks creados en chunk_document stage.
    """
    logger.info("build_fts_index_started", document_id=document_id)

    try:
        session = session_factory()
        try:
            stmt = select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.chunk_type == "text",
            )
            chunks = session.execute(stmt).scalars().all()

            fts_entries = []
            for chunk in chunks:
                fts_entry = DocumentFTSIndex(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    level=chunk.level,
                    search_vector="",
                )
                fts_entries.append(fts_entry)

            # Generar tsvector real usando PostgreSQL nativo
            if fts_entries:
                chunk_ids = [c.id for c in fts_entries]
                raw_sql = """
                    UPDATE document_fts_index
                    SET search_vector = to_tsvector('spanish', content)
                    FROM document_chunks
                    WHERE document_fts_index.chunk_id = document_chunks.id
                      AND document_chunks.id = ANY(:ids)
                """
                session.execute(sa_text(raw_sql), {"ids": chunk_ids})
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
        logger.warning("build_fts_index_failed (optional)", document_id=document_id, error=str(exc))
        return {"indexed_chunks": 0, "warning": str(exc)}


@celery_app.task(
    name="documents.generate_summaries",
    bind=True,
    max_retries=3,
    acks_late=True,
    time_limit=3600,
    soft_time_limit=3300,
)
def generate_summaries(self, document_id: str, tenant_id: str) -> dict:
    """
    Generar resúmenes jerárquicos usando el LLM cliente:
    1. Resúmenes por sección (nivel 2)
    2. Resumen del documento completo (nivel 3)
    """
    logger.info("generate_summaries_started", document_id=document_id)

    session = session_factory()
    try:
        stmt = select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.level == 1,
        )
        level1_chunks = session.execute(stmt).scalars().all()

        if not level1_chunks:
            return {"status": "skipped", "reason": "no level 1 chunks found"}

        # Importar LLM client (sincrono, compatible con Celery)
        from ai_platform.orchestrator.llm_client import LLMClient

        llm = LLMClient()
        summaries = {"level2_count": 0, "level3_summaries": []}

        BATCH_SIZE = 5
        level2_results = []

        for i in range(0, len(level1_chunks), BATCH_SIZE):
            batch_chunks = level1_chunks[i : i + BATCH_SIZE]
            batch_text = "\n\n".join(c.content[:2000] for c in batch_chunks)

            prompt = (
                "Eres un asistente que genera resúmenes concisos de texto. "
                f"Resume el siguiente texto en máximo 3 párrafos, conservando los datos clave:\n\n{batch_text}"
            )

            try:
                result = llm.chat(prompt, tenant_id=tenant_id)
                content = result.get("content", "")
                if content and content.strip():
                    level2_summary = DocumentChunk(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        chunk_index=i // BATCH_SIZE,
                        level=2,
                        chunk_type="summary",
                        content=content.strip(),
                        metadata_json={
                            "source_chunk_indices": [c.chunk_index for c in batch_chunks],
                            "source_tenant_id": tenant_id,
                        },
                    )
                    session.add(level2_summary)
                    session.flush()
                    level2_results.append(level2_summary)
                    summaries["level2_count"] += 1
            except Exception as e:
                logger.warning(f"generate_summary_section_failed, batch={i}: {e}")
                continue

        # Generar resumen global del documento (nivel 3)
        if level2_results:
            global_text = "\n\n".join(
                c.content[:2000] for c in level2_results[:10]
            )
            prompt_global = (
                "Eres un asistente que genera un resumen ejecutivo de un documento. "
                "Con base en los siguientes resúmenes de secciones, genera un resumen global "
                "de máximo 5 párrafos que capture los puntos clave del documento:\n\n" + global_text
            )

            try:
                result = llm.chat(prompt_global, tenant_id=tenant_id)
                content = result.get("content", "")
                if content and content.strip():
                    global_summary = DocumentChunk(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        chunk_index=999,
                        level=3,
                        chunk_type="document_summary",
                        content=content.strip(),
                        metadata_json={
                            "source_level2_count": len(level2_results),
                            "source_tenant_id": tenant_id,
                        },
                    )
                    session.add(global_summary)
                    summaries["level3_summaries"].append(content.strip()[:200])
            except Exception as e:
                logger.warning(f"generate_summary_global_failed: {e}")

        summaries["status"] = "completed"
        summaries["total_level2"] = summaries["level2_count"]
        summaries["total_level3"] = len(summaries["level3_summaries"])

        session.commit()

        logger.info(
            "generate_summaries_completed",
            document_id=document_id,
            level2_count=summaries["level2_count"],
            level3_count=len(summaries["level3_summaries"]),
        )

        return summaries

    except Exception as exc:
        logger.error("generate_summaries_failed", document_id=document_id, error=str(exc))
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()
        try:
            llm.close()
        except Exception:
            pass


@celery_app.task(
    name="documents.mark_completed",
    bind=True,
    max_retries=1,
    acks_late=True,
    time_limit=60,
)
def mark_completed(self, document_id: str, tenant_id: str, stats: dict) -> dict:
    """Marcar documento como completado y registrar stats."""
    logger.info("mark_completed", document_id=document_id, stats=stats)

    try:
        _update_document(
            document_id,
            {
                "status": "completed",
                "completed_at": None,
                **stats,
            },
        )
        return {"status": "completed", "document_id": document_id}

    except Exception as exc:
        logger.error("mark_completed_failed", document_id=document_id, error=str(exc))
        raise self.retry(exc=exc, countdown=30) from None


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
) -> dict:
    """
    Pipeline principal de ingestion de documentos.
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
            ocr_result = ocr_all_pages.delay(document_id, tenant_id, extract_data.get("page_count", 1))
            _ = ocr_result.get(timeout=600)

        # Stage 3: Chunk (lee de la BD, no del Celery result)
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
        _ = summary_result.get(timeout=3600)

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