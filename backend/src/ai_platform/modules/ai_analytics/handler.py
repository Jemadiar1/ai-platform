"""
Handler para el módulo ai-analytics.

Ejecuta acciones de analítica, investigación web, OCR, reportes e
ingestión de documentos. Cada acción delega en un servicio productivo
existente (web_research_service, report_renderer, vision_ocr,
document_chunker, document_storage, embedding_service).

Las acciones se dividen en:

- Investigación: web_research, web_fetch, web_browser
- Reportes: generate_report, render_report
- OCR: ocr_extract, chart_detect
- Documentos: document_ingest, document_chunk, document_fts_search
- Fallback: default (conversacional con LLM)

"""

import asyncio
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Handler:
    """
    Handler para el módulo ai-analytics.

    Acciones soportadas:
        - web_research: investigar fuentes web
        - web_fetch: fetch de una URL específica
        - web_browser: fetch con navegador headless
        - generate_report: generar reporte analítico
        - render_report: renderizar en múltiples formatos
        - ocr_extract: extracción OCR de imágenes
        - chart_detect: detección de gráficos en imágenes
        - document_ingest: subir y procesar documentos
        - document_chunk: dividir documentos en chunks
        - document_fts_search: buscar texto completo en documentos indexados
        - default: fallback conversacional con LLM
    """

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar acción del módulo ai-analytics.

        Parámetros:
            payload: Dict con 'action' y parámetros analíticos

        Retorna:
            Dict con status, response y metadata
        """
        action = payload.get("action", "default")
        params = payload.get("params", {})
        metadata = payload.get("metadata", {})
        tenant_id = metadata.get("tenant_id", params.get("tenant_id", "unknown"))

        logger.info(f"Ejecutando ai-analytics.{action} para tenant {tenant_id}")

        dispatch = {
            "web_research": self._web_research,
            "web_fetch": self._web_fetch,
            "web_browser": self._web_browser,
            "generate_report": self._generate_report,
            "render_report": self._render_report,
            "ocr_extract": self._ocr_extract,
            "chart_detect": self._chart_detect,
            "document_ingest": self._document_ingest,
            "document_chunk": self._document_chunk,
            "document_fts_search": self._document_fts_search,
            "default": self._default,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {
                "action": action,
                "status": "failed",
                "error": f"Acción '{action}' no encontrada en ai-analytics",
                "note": "Acciones disponibles: web_research, web_fetch, web_browser, generate_report, render_report, ocr_extract, chart_detect, document_ingest, document_chunk, document_fts_search, default",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            result = handler(params, metadata, tenant_id)
            result["action"] = action
            result["timestamp"] = datetime.utcnow().isoformat()
            return result
        except Exception as e:
            logger.error(f"Error ejecutando ai-analytics.{action}: {e}", exc_info=True)
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    # =========================================================================
    # Investigación web
    # =========================================================================

    def _web_research(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Investigar fuentes web con búsqueda multi-fuente."""
        from ai_platform.services.web_research_service import web_research_service

        query = params.get("query", "")
        if not query:
            return {
                "status": "failed",
                "response": "Se requiere un query de investigación",
                "error": "query no proporcionado",
            }

        try:
            loop = asyncio.new_event_loop()
            try:
                research_results = loop.run_until_complete(
                    web_research_service.fetch_search(
                        query=query,
                        tenant_id=tenant_id,
                        source_by="ai-analytics",
                    )
                )

                sources = research_results or []
                summary_parts = []
                for i, source in enumerate(sources[:5], 1):
                    title = source.title if hasattr(source, "title") else source.get("title", "Sin título")
                    snippet = source.content[:300] if hasattr(source, "content") else source.get("content", "")[:300]
                    url = source.url if hasattr(source, "url") else source.get("url", "")
                    summary_parts.append(f"{i}. {title} — {snippet} ({url})")

                summary = "\n\n".join(summary_parts)
                if not summary:
                    summary = "No se encontraron resultados para la investigación."

                return {
                    "status": "success",
                    "response": summary,
                    "source_count": len(sources),
                    "query": query,
                }
            finally:
                loop.close()
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error investigando: {e}",
                "error": str(e),
            }

    def _web_fetch(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Fetch y parsear contenido de una URL específica."""
        from ai_platform.services.web_research_service import web_research_service

        url = params.get("url", "")
        if not url:
            return {
                "status": "failed",
                "response": "Se requiere una URL para fetch",
                "error": "url no proporcionada",
            }

        try:
            loop = asyncio.new_event_loop()
            try:
                fetch_result = loop.run_until_complete(
                    web_research_service.fetch_url(
                        url=url,
                        tenant_id=tenant_id,
                        source_by="ai-analytics",
                    )
                )

                content = fetch_result.content if hasattr(fetch_result, "content") else fetch_result.get("content", "")
                title = (
                    fetch_result.title if hasattr(fetch_result, "title") else fetch_result.get("title", "Sin título")
                )
                if len(content) > 4000:
                    content = content[:4000] + "... [truncado]"

                status_code = None
                if hasattr(fetch_result, "status_code"):
                    status_code = fetch_result.status_code
                elif isinstance(fetch_result, dict):
                    status_code = fetch_result.get("status_code")

                return {
                    "status": "success",
                    "response": f"## {title}\n\n{content}",
                    "source_url": url,
                    "status_code": status_code,
                }
            finally:
                loop.close()
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error fetch: {e}",
                "error": str(e),
            }

    def _web_browser(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Fetch con navegador headless para contenido dinámico."""
        from ai_platform.services.web_research_service import web_research_service

        url = params.get("url", "")
        if not url:
            return {
                "status": "failed",
                "response": "Se requiere una URL para browser session",
                "error": "url no proporcionada",
            }

        try:
            loop = asyncio.new_event_loop()
            try:
                browser_result = loop.run_until_complete(
                    web_research_service.browser_session(
                        url=url,
                        tenant_id=tenant_id,
                        source_by="ai-analytics",
                        extract_content=True,
                    )
                )

                content = (
                    browser_result.content if hasattr(browser_result, "content") else browser_result.get("content", "")
                )
                title = (
                    browser_result.page_title
                    if hasattr(browser_result, "page_title")
                    else browser_result.get("title", "Sin título")
                )
                if content and len(content) > 4000:
                    content = content[:4000] + "... [truncado]"

                screenshot = None
                if hasattr(browser_result, "screenshot_base64"):
                    screenshot = browser_result.screenshot_base64
                elif isinstance(browser_result, dict):
                    screenshot = browser_result.get("screenshot")

                return {
                    "status": "success",
                    "response": f"## {title}\n\n{content}" if content else f"## {title}",
                    "source_url": url,
                    "screenshot": screenshot,
                }
            finally:
                loop.close()
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error browser session: {e}",
                "error": str(e),
            }

    # =========================================================================
    # Reportes
    # =========================================================================

    def _generate_report(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Generar reporte analítico con datos de múltiples fuentes."""
        from ai_platform.services.report_models import (
            BrandTheme,
            ReportFormat,
            ReportSpec,
            Section,
        )
        from ai_platform.services.report_renderer import ReportRendererService

        report_spec = params.get("report_spec", {})
        if not report_spec:
            return {
                "status": "failed",
                "response": "Se requiere un report_spec con title y sections",
                "error": "report_spec no proporcionado",
            }

        try:
            theme_data = report_spec.get("theme", {})
            theme = BrandTheme(
                primary_color=theme_data.get("primary_color", "#1a73e8"),
                secondary_color=theme_data.get("secondary_color", "#5f6368"),
                font_family=theme_data.get("font_family", "Arial, sans-serif"),
                company_name=theme_data.get("company_name", "NeuralCrew Labs"),
            )

            sections_data = report_spec.get("sections", [])
            sections = [
                Section(
                    id=s.get("id", ""),
                    title=s.get("title", ""),
                    content=s.get("content", ""),
                )
                for s in sections_data
            ]

            report_spec_obj = ReportSpec(
                title=report_spec.get("title", "Reporte"),
                audience=report_spec.get("audience", ""),
                sections=sections,
                theme=theme,
            )

            renderer = ReportRendererService()
            formats = [ReportFormat.HTML, ReportFormat.PDF]
            outputs = renderer.render(tenant_id, report_spec_obj, formats=formats)

            return {
                "status": "success",
                "response": f"Reporte '{report_spec_obj.title}' generado exitosamente. Formatos disponibles: {', '.join(outputs.keys())}",
                "formats_available": list(outputs.keys()),
                "file_sizes": {k: len(v) for k, v in outputs.items()},
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error generando reporte: {e}",
                "error": str(e),
            }

    def _render_report(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Renderizar reportes en múltiples formatos (PDF, DOCX, XLSX, CSV)."""
        from ai_platform.services.report_models import (
            BrandTheme,
            ReportFormat,
            ReportSpec,
            Section,
        )
        from ai_platform.services.report_renderer import ReportRendererService

        report_spec = params.get("report_spec", {})
        format_strings = params.get("formats", ["html", "pdf", "docx", "xlsx"])

        if not report_spec:
            return {
                "status": "failed",
                "response": "Se requiere un report_spec para renderizar",
                "error": "report_spec no proporcionado",
            }

        try:
            # Convert string format names to ReportFormat enum values
            format_map = {
                "html": ReportFormat.HTML,
                "pdf": ReportFormat.PDF,
                "docx": ReportFormat.DOCX,
                "xlsx": ReportFormat.XLSX,
                "csv": ReportFormat.CSV,
            }
            formats = [format_map[f] for f in format_strings if f in format_map]
            if not formats:
                formats = [ReportFormat.HTML, ReportFormat.PDF]

            theme_data = report_spec.get("theme", {})
            theme = BrandTheme(
                primary_color=theme_data.get("primary_color", "#1a73e8"),
                secondary_color=theme_data.get("secondary_color", "#5f6368"),
                font_family=theme_data.get("font_family", "Arial, sans-serif"),
                company_name=theme_data.get("company_name", "NeuralCrew Labs"),
            )

            sections_data = report_spec.get("sections", [])
            sections = [
                Section(
                    id=s.get("id", ""),
                    title=s.get("title", ""),
                    content=s.get("content", ""),
                )
                for s in sections_data
            ]

            report_spec_obj = ReportSpec(
                title=report_spec.get("title", "Reporte"),
                audience=report_spec.get("audience", ""),
                sections=sections,
                theme=theme,
            )

            renderer = ReportRendererService()
            outputs = renderer.render(tenant_id, report_spec_obj, formats=formats)

            return {
                "status": "success",
                "response": f"Reporte renderizado en {len(outputs)} formatos: {', '.join(outputs.keys())}",
                "formats_available": list(outputs.keys()),
                "file_sizes": {k: len(v) for k, v in outputs.items()},
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error renderizando reporte: {e}",
                "error": str(e),
            }

    # =========================================================================
    # OCR
    # =========================================================================

    def _ocr_extract(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Extracción de texto OCR de imágenes y documentos escaneados."""
        from ai_platform.services.vision_ocr import VisionOCRService

        image_data = params.get("image_data", b"")
        if not image_data:
            # Try base64 encoded image
            b64_data = params.get("image_base64", "")
            if b64_data:
                import base64

                try:
                    image_data = base64.b64decode(b64_data)
                except Exception:
                    image_data = b""
            elif isinstance(params.get("image_data"), str) and len(params["image_data"]) > 10:
                try:
                    image_data = params["image_data"].encode("utf-8")
                except Exception:
                    image_data = b""

        if not image_data or (isinstance(image_data, str) and len(image_data) < 10):
            return {
                "status": "failed",
                "response": "Se requieren datos de imagen para OCR",
                "error": "image_data no proporcionado",
            }

        try:
            # VisionOCRService.analyze() is synchronous, no event loop needed
            service = VisionOCRService()
            ocr_result = service.analyze(
                tenant_id=tenant_id,
                image_bytes=image_data if isinstance(image_data, bytes) else image_data.encode("utf-8"),
                filename=params.get("filename"),
                include_charts=True,
            )

            return {
                "status": "success",
                "response": ocr_result.text if ocr_result else "No se extrajo texto de la imagen",
                "confidence": ocr_result.confidence if ocr_result else 0,
                "engine": ocr_result.engine if ocr_result else "unknown",
                "charts_found": len(ocr_result.charts) if ocr_result else 0,
                "warnings": ocr_result.warnings if ocr_result else [],
                "storage_id": ocr_result.storage_id if ocr_result else None,
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error OCR: {e}",
                "error": str(e),
            }

    def _chart_detect(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Detección y análisis de gráficos/charts en imágenes."""
        from ai_platform.services.vision_ocr import VisionOCRService

        image_data = params.get("image_data", b"")
        if not image_data:
            # Try base64 encoded image
            b64_data = params.get("image_base64", "")
            if b64_data:
                import base64

                try:
                    image_data = base64.b64decode(b64_data)
                except Exception:
                    image_data = b""
            elif isinstance(params.get("image_data"), str) and len(params["image_data"]) > 10:
                try:
                    image_data = params["image_data"].encode("utf-8")
                except Exception:
                    image_data = b""

        if not image_data or (isinstance(image_data, str) and len(image_data) < 10):
            return {
                "status": "failed",
                "response": "Se requieren datos de imagen para detectar gráficos",
                "error": "image_data no proporcionado",
            }

        try:
            # VisionOCRService.analyze() is synchronous, no event loop needed
            service = VisionOCRService()
            ocr_result = service.analyze(
                tenant_id=tenant_id,
                image_bytes=image_data if isinstance(image_data, bytes) else image_data.encode("utf-8"),
                filename=params.get("filename"),
                include_charts=True,
            )

            charts = ocr_result.charts if ocr_result else []
            chart_summary = ""
            for i, chart in enumerate(charts[:5], 1):
                chart_summary += f"{i}. {chart.get('title', 'Sin título')} — {chart.get('description', '')}\n"

            return {
                "status": "success",
                "response": chart_summary if chart_summary else "No se detectaron gráficos en la imagen",
                "chart_count": len(charts),
                "charts": charts,
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error detectando gráficos: {e}",
                "error": str(e),
            }

    # =========================================================================
    # Documentos
    # =========================================================================

    def _document_ingest(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Subir y procesar documentos (PDF, DOCX, imágenes)."""
        from ai_platform.services.document_storage import save_uploaded_file

        file_bytes = params.get("file_bytes", b"")
        original_filename = params.get("original_filename", "document")

        if not file_bytes:
            # Try base64 encoded file
            b64_data = params.get("file_base64", "")
            if b64_data:
                import base64

                try:
                    file_bytes = base64.b64decode(b64_data)
                except Exception:
                    file_bytes = b""

        if not file_bytes or (isinstance(file_bytes, str) and len(file_bytes) < 10):
            return {
                "status": "failed",
                "response": "Se requiere contenido de archivo para ingest",
                "error": "file_bytes no proporcionado",
            }

        try:
            file_path = save_uploaded_file(
                file_bytes=file_bytes if isinstance(file_bytes, bytes) else file_bytes.encode("utf-8"),
                original_filename=original_filename,
                tenant_id=tenant_id,
            )

            return {
                "status": "success",
                "response": f"Documento '{original_filename}' guardado exitosamente",
                "file_path": file_path,
                "size_bytes": len(file_bytes) if isinstance(file_bytes, bytes) else len(file_bytes.encode("utf-8")),
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error ingesting documento: {e}",
                "error": str(e),
            }

    def _document_chunk(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Dividir documentos en chunks con estrategias de chunking."""
        from ai_platform.services.document_chunker import DocumentChunker

        text = params.get("text", "")
        if not text:
            return {
                "status": "failed",
                "response": "Se requiere texto para chunking",
                "error": "text no proporcionado",
            }

        try:
            chunker = DocumentChunker()
            chunks = chunker.chunk_hybrid(text)

            chunk_summaries = []
            for i, chunk in enumerate(chunks[:10], 1):
                preview = chunk.content[:200]
                if len(chunk.content) > 200:
                    preview += "..."
                chunk_summaries.append(f"Chunk {i} (nivel {chunk.level}, {len(chunk.content)} chars): {preview}")

            summary = "\n\n".join(chunk_summaries)
            if not summary:
                summary = "No se generaron chunks del documento"

            return {
                "status": "success",
                "response": summary,
                "total_chunks": len(chunks),
                "strategy": "hybrid",
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error chunking: {e}",
                "error": str(e),
            }

    def _document_fts_search(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Buscar texto completo en documentos indexados usando embeddings o FTS."""
        from sqlalchemy import select

        from ai_platform.database import make_session
        from ai_platform.models.db import DocumentChunk

        query = params.get("query", "")
        if not query:
            return {
                "status": "failed",
                "response": "Se requiere un query de búsqueda",
                "error": "query no proporcionado",
            }

        try:
            results = []
            with make_session() as db:
                stmt = (
                    select(DocumentChunk)
                    .where(DocumentChunk.tenant_id == tenant_id, DocumentChunk.content.ilike(f"%{query}%"))
                    .order_by(DocumentChunk.chunk_index)
                    .limit(20)
                )
                chunks = db.execute(stmt).scalars().all()

                for chunk in chunks:
                    highlight = chunk.content
                    idx = highlight.lower().find(query.lower())
                    if idx >= 0:
                        start = max(0, idx - 100)
                        end = min(len(highlight), idx + len(query) + 100)
                        highlight = (
                            ("..." if start > 0 else "")
                            + highlight[start:end]
                            + ("..." if end < len(highlight) else "")
                        )
                    results.append(
                        {
                            "text": highlight,
                            "chunk_index": chunk.chunk_index,
                            "level": chunk.level,
                            "chunk_type": chunk.chunk_type,
                        }
                    )

            if not results:
                return {
                    "status": "success",
                    "response": "No se encontraron documentos relevantes para la búsqueda.",
                    "query": query,
                    "results": [],
                }

            response_parts = []
            for i, r in enumerate(results[:5], 1):
                response_parts.append(
                    f"{i}. Chunk #{r['chunk_index']} (nível {r['level']}, {r['chunk_type']}):\n{r['text']}"
                )

            return {
                "status": "success",
                "response": "\n\n".join(response_parts),
                "query": query,
                "total_indexed": len(chunks) if "chunks" in dir() else 0,
                "result_count": len(results),
                "results": results[:5],
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error en búsqueda: {e}",
                "error": str(e),
            }

    # =========================================================================
    # Fallback
    # =========================================================================

    def _default(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Fallback conversacional con LLM cuando no hay acción específica."""
        from ai_platform.orchestrator.llm_client import LLMClient

        message_text = params.get("message_text", "")
        if not message_text:
            message_text = params.get("params", {}).get("message_text", "")

        if not message_text:
            return {
                "status": "success",
                "response": "¿En qué puedo ayudarte con analítica? Puedo investigar fuentes web, generar reportes, hacer OCR de imágenes, o procesar documentos.",
            }

        try:
            loop = asyncio.new_event_loop()
            try:
                llm = LLMClient()
                response = loop.run_until_complete(
                    llm.chat(
                        message_text=message_text,
                        tenant_id=tenant_id,
                    )
                )
                return {
                    "status": "success",
                    "response": response,
                }
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Error en default handler: {e}")
            return {
                "status": "success",
                "response": "No pude procesar tu solicitud. ¿Puedes ser más específico? Puedo ayudarte con investigación web, reportes, OCR o documentos.",
            }
