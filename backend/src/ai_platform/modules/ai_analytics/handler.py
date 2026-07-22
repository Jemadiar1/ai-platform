"""
Handler para el módulo ai-analytics.

Ejecuta acciones de analítica, investigación web, OCR, reportes e
ingestión de documentos. Cada acción delega en un servicio productivo
existente (web_research_service, report_renderer, vision_ocr,
document_chunker, document_storage).

Las acciones se dividen en:

- Investigación: web_research, web_fetch, web_browser
- Reportes: generate_report, render_report
- OCR: ocr_extract, chart_detect
- Documentos: document_ingest, document_chunk
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
            "default": self._default,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {
                "action": action,
                "status": "failed",
                "error": f"Acción '{action}' no encontrada en ai-analytics",
                "note": "Acciones disponibles: web_research, web_fetch, web_browser, generate_report, render_report, ocr_extract, chart_detect, document_ingest, document_chunk, default",
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
                research_result = loop.run_until_complete(
                    web_research_service.fetch_search(
                        query=query,
                        tenant_id=tenant_id,
                        source_by="ai-analytics",
                    )
                )

                sources = research_result.get("results", [])
                summary_parts = []
                for i, source in enumerate(sources[:5], 1):
                    title = source.get("title", "Sin título")
                    snippet = source.get("snippet", "")
                    url = source.get("url", "")
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

                content = fetch_result.get("content", "")
                title = fetch_result.get("title", "Sin título")
                if len(content) > 4000:
                    content = content[:4000] + "... [truncado]"

                return {
                    "status": "success",
                    "response": f"## {title}\n\n{content}",
                    "source_url": url,
                    "status_code": fetch_result.get("status_code"),
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

                content = browser_result.get("content", "")
                title = browser_result.get("title", "Sin título")
                if len(content) > 4000:
                    content = content[:4000] + "... [truncado]"

                return {
                    "status": "success",
                    "response": f"## {title}\n\n{content}",
                    "source_url": url,
                    "screenshot": browser_result.get("screenshot"),
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
        from ai_platform.services.report_models import BrandTheme, ReportSpec
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
            sections = []
            for s in sections_data:
                section = {
                    "id": s.get("id", ""),
                    "title": s.get("title", ""),
                    "content": s.get("content", ""),
                }
                sections.append(section)

            report_spec_obj = ReportSpec(
                title=report_spec.get("title", "Reporte"),
                audience=report_spec.get("audience", ""),
                sections=sections,
                theme=theme,
            )

            renderer = ReportRendererService()
            outputs = renderer.render(tenant_id, report_spec_obj, formats=["html", "pdf"])

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
        from ai_platform.services.report_models import BrandTheme, ReportSpec
        from ai_platform.services.report_renderer import ReportRendererService

        report_spec = params.get("report_spec", {})
        formats = params.get("formats", ["html", "pdf", "docx", "xlsx"])

        if not report_spec:
            return {
                "status": "failed",
                "response": "Se requiere un report_spec para renderizar",
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
            sections = []
            for s in sections_data:
                section = {
                    "id": s.get("id", ""),
                    "title": s.get("title", ""),
                    "content": s.get("content", ""),
                }
                sections.append(section)

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
        from ai_platform.services.vision_ocr import analyze

        image_data = params.get("image_data", "")
        if not image_data:
            return {
                "status": "failed",
                "response": "Se requieren datos de imagen para OCR",
                "error": "image_data no proporcionado",
            }

        try:
            loop = asyncio.new_event_loop()
            try:
                ocr_result = loop.run_until_complete(
                    analyze(
                        image_data=image_data,
                        tenant_id=tenant_id,
                        source_format=params.get("source_format", "image"),
                    )
                )

                return {
                    "status": "success",
                    "response": ocr_result.text if ocr_result else "No se extrajo texto de la imagen",
                    "confidence": ocr_result.overall_confidence if ocr_result else 0,
                    "engine_used": ocr_result.engine_used if ocr_result else "unknown",
                    "charts_found": len(ocr_result.charts) if ocr_result else 0,
                    "warnings": ocr_result.warnings if ocr_result else [],
                }
            finally:
                loop.close()
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error OCR: {e}",
                "error": str(e),
            }

    def _chart_detect(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        """Detección y análisis de gráficos/charts en imágenes."""
        from ai_platform.services.vision_ocr import analyze

        image_data = params.get("image_data", "")
        if not image_data:
            return {
                "status": "failed",
                "response": "Se requieren datos de imagen para detectar gráficos",
                "error": "image_data no proporcionado",
            }

        try:
            loop = asyncio.new_event_loop()
            try:
                ocr_result = loop.run_until_complete(
                    analyze(
                        image_data=image_data,
                        tenant_id=tenant_id,
                        source_format=params.get("source_format", "image"),
                    )
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
            finally:
                loop.close()
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
            return {
                "status": "failed",
                "response": "Se requiere contenido de archivo para ingest",
                "error": "file_bytes no proporcionado",
            }

        try:
            file_path = save_uploaded_file(
                file_bytes=file_bytes,
                original_filename=original_filename,
                tenant_id=tenant_id,
            )

            return {
                "status": "success",
                "response": f"Documento '{original_filename}' guardado exitosamente",
                "file_path": file_path,
                "size_bytes": len(file_bytes),
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
