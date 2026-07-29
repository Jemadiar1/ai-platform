import inspect
"""
Handler para el módulo ai-documents.

Ejecuta acciones de generación de archivos profesionales:
- render_docx: Generar documento DOCX profesional
- render_xlsx: Generar hoja de cálculo XLSX profesional
- render_pptx: Generar presentación PPTX profesional
- render_png:  Generar imagen PNG (gráfico, banner, infografía)
- render_pdf:  Generar documento PDF profesional
- render_all:  Generar todos los formatos disponibles

"""

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Handler:
    """Handler para el módulo ai-documents."""

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Ejecutar acción del módulo ai-documents."""
        action = payload.get("action", "default")
        params = payload.get("params", {})
        metadata = payload.get("metadata", {})
        tenant_id = metadata.get("tenant_id", params.get("tenant_id", "unknown"))

        logger.info(f"Ejecutando ai-documents.{action} para tenant {tenant_id}")

        dispatch = {
            "render_docx": self._render_docx,
            "render_xlsx": self._render_xlsx,
            "render_pptx": self._render_pptx,
            "render_png": self._render_png,
            "render_pdf": self._render_pdf,
            "render_all": self._render_all,
            "generate_document": self._render_document,
            "create_document": self._render_document,
            "generate_docx": self._render_docx,
            "create_docx": self._render_docx,
            "generate_xlsx": self._render_xlsx,
            "generate_pptx": self._render_pptx,
            "generate_pdf": self._render_pdf,
            "default": self._render_document,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {
                "action": action,
                "status": "failed",
                "error": f"Acción '{action}' no encontrada en ai-documents",
                "note": "Acciones disponibles: render_docx, render_xlsx, render_pptx, render_png, render_pdf, render_all, default",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            if inspect.iscoroutinefunction(handler):
                result = await handler(params, metadata, tenant_id)
            else:
                res = handler(params, metadata, tenant_id)
                result = await res if inspect.iscoroutine(res) else res
            result["action"] = action
            result["timestamp"] = datetime.utcnow().isoformat()
            return result
        except Exception as e:
            logger.error(f"Error ejecutando ai-documents.{action}: {e}", exc_info=True)
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    async def _ensure_rich_content(self, params: dict, tenant_id: str) -> dict:
        """Synthesize rich structured markdown if content lacks markdown headings or is raw chat history."""
        content = params.get("content", "") or params.get("prompt", "") or ""
        subject = params.get("subject", "") or params.get("title", "") or "Documento Profesional"

        has_headings = "# " in content or "## " in content or "### " in content
        is_short_or_chat = len(content.strip()) < 150 or "USER:" in content or content == subject

        if not has_headings or is_short_or_chat:
            from ai_platform.orchestrator.llm_client import get_llm_client

            sys_prompt = (
                "Eres el redactor ejecutivo principal de NeuralCrew Labs.\n"
                "Tu objetivo es redactar un DOCUMENTO COMPLETO Y PROFESIONAL en formato Markdown estricto.\n"
                "Debes redactar contenido real, detallado, rico y útil. NUNCA devuelvas solo plantillas vacías o listas vacías.\n\n"
                "REGLAS DE ESTRUCTURA MARKDOWN:\n"
                "1. Encabezado de Nivel 1: '# Título Principal del Documento'\n"
                "2. '## Resumen Ejecutivo': Un resumen bien redactado del propósito y los objetivos.\n"
                "3. '## Especificaciones Técnicas y Alcance': Detalles técnicos, tono, público objetivo y requisitos.\n"
                "4. '## Contenido Principal / Guión': Si es un guión, incluye los personajes en **negrita**, acotaciones de escena entre *paréntesis* y diálogos redactados completos. Si es un informe, incluye secciones y análisis profundo.\n"
                "5. '## Tabla de Métricas y Presupuesto': Una tabla Markdown completa (| Columna 1 | Columna 2 | Columna 3 |) con datos razonables.\n"
                "6. '## Conclusiones y Próximos Pasos': Recomendaciones de ejecución.\n\n"
                "Redacta todo en español elegante y corporativo."
            )

            user_prompt = f"Tema o Requerimiento del Usuario: {subject}\n\nContexto / Historial previo:\n{content}"

            try:
                llm = get_llm_client()
                rich_text = await llm.generate_text(user_prompt, sys_prompt)
                if rich_text and len(rich_text) > 100:
                    params["content"] = rich_text
            except Exception as e:
                logger.warning(f"Error generando contenido enriquecido con LLM: {e}")

        return params

    # =========================================================================
    # Render actions
    # =========================================================================

    async def _render_docx(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        params = await self._ensure_rich_content(params, tenant_id)
        g = Generators(tenant_id)
        return g.render_docx(tenant_id, params)

    async def _render_xlsx(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        params = await self._ensure_rich_content(params, tenant_id)
        g = Generators(tenant_id)
        return g.render_xlsx(tenant_id, params)

    async def _render_pptx(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        params = await self._ensure_rich_content(params, tenant_id)
        g = Generators(tenant_id)
        return g.render_pptx(tenant_id, params)

    async def _render_png(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        g = Generators(tenant_id)
        return g.render_png(tenant_id, params)

    async def _render_pdf(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        params = await self._ensure_rich_content(params, tenant_id)
        g = Generators(tenant_id)
        return g.render_pdf(tenant_id, params)

    async def _render_all(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        params = await self._ensure_rich_content(params, tenant_id)
        g = Generators(tenant_id)
        return g.render_all(tenant_id, params)

    async def _render_document(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        params = await self._ensure_rich_content(params, tenant_id)
        fmt = (params.get("format") or params.get("file_type") or params.get("type") or "docx").lower()
        if "xlsx" in fmt or "excel" in fmt or "sheet" in fmt:
            return await self._render_xlsx(params, metadata, tenant_id)
        elif "pptx" in fmt or "powerpoint" in fmt or "presentation" in fmt or "slide" in fmt:
            return await self._render_pptx(params, metadata, tenant_id)
        elif "pdf" in fmt:
            return await self._render_pdf(params, metadata, tenant_id)
        elif "png" in fmt or "image" in fmt:
            return await self._render_png(params, metadata, tenant_id)
        else:
            return await self._render_docx(params, metadata, tenant_id)

    # =========================================================================
    # Fallback
    # =========================================================================

    def _default(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        logger.info(f"ai-documents.default para tenant {tenant_id}")
        message_text = metadata.get("message_text", "")
        if message_text:
            return {
                "action": "default",
                "status": "success",
                "result": f"Para generar un documento, especifica el formato: render_docx, render_xlsx, render_pptx, render_png, render_pdf o render_all.\n\nTu mensaje: {message_text}",
            }
        return {
            "action": "default",
            "status": "info",
            "available_actions": [
                "render_docx",
                "render_xlsx",
                "render_pptx",
                "render_png",
                "render_pdf",
                "render_all",
            ],
        }