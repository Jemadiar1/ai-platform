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

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
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
            "default": self._default,
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
            result = handler(params, metadata, tenant_id)
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

    # =========================================================================
    # Render actions
    # =========================================================================

    def _render_docx(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        g = Generators(tenant_id)
        return g.render_docx(tenant_id, params)

    def _render_xlsx(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        g = Generators(tenant_id)
        return g.render_xlsx(tenant_id, params)

    def _render_pptx(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        g = Generators(tenant_id)
        return g.render_pptx(tenant_id, params)

    def _render_png(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        g = Generators(tenant_id)
        return g.render_png(tenant_id, params)

    def _render_pdf(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        g = Generators(tenant_id)
        return g.render_pdf(tenant_id, params)

    def _render_all(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        from ai_platform.modules.ai_documents.generators import Generators

        g = Generators(tenant_id)
        return g.render_all(tenant_id, params)

    # =========================================================================
    # Fallback
    # =========================================================================

    def _default(self, params: dict, metadata: dict, tenant_id: str) -> dict:
        logger.info(f"ai-documents.default para tenant {tenant_id}")
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