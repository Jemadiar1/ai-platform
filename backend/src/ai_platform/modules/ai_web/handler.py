"""
Handler para el módulo ai-web.

Genera páginas web con IA: landing pages, sitios corporativos,
e-commerce, páginas de producto y más.

Las acciones se dividen en:

- generate_page: generar página web completa con HTML/CSS
- default: fallback conversacional con LLM

"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Handler:
    """
    Handler para el módulo ai-web.

    GENERA PÁGINAS WEB con IA.
    Incluye: landing pages, sitios corporativos, e-commerce.

    Acciones soportadas:
        - generate_page: Generar página web o landing page
        - default: Fallback conversacional con LLM
    """

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar acción del módulo ai-web.

        Parámetros:
            payload: Dict con 'action' y parámetros de página web

        Retorna:
            Dict con status, response y metadata
        """
        action = payload.get("action", "default")
        params = payload.get("params", {})
        metadata = payload.get("metadata", {})
        tenant_id = metadata.get("tenant_id", params.get("tenant_id", "unknown"))

        logger.info(f"Ejecutando ai-web.{action} para tenant {tenant_id}")

        dispatch = {
            "generate_page": self._generate_page,
            "default": self._default,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {
                "action": action,
                "status": "failed",
                "error": f"Acción '{action}' no encontrada en ai-web",
                "note": "Acciones disponibles: generate_page, default",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            result = handler(params, metadata, tenant_id)
            result["action"] = action
            result["timestamp"] = datetime.utcnow().isoformat()
            return result
        except Exception as e:
            logger.error(f"Error ejecutando ai-web.{action}: {e}", exc_info=True)
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    # =========================================================================
    # Generación de páginas web
    # =========================================================================

    def _generate_page(
        self, params: dict, metadata: dict, tenant_id: str
    ) -> dict:
        """Generar página web completa con HTML/CSS responsivo."""
        from ai_platform.orchestrator.llm_client import LLMClient

        page_type = params.get("page_type", "landing")
        brand_name = params.get("brand_name", "")
        industry = params.get("industry", "")
        colors = params.get("colors", {})
        content = params.get("content", "")
        sections_requested = params.get("sections", [])
        additional_context = params.get("context", "")
        kwargs = params.get("kwargs", {})

        # Extraer parámetros de kwargs
        if not brand_name and "brand_name" in kwargs:
            brand_name = kwargs.pop("brand_name")
        if not industry and "industry" in kwargs:
            industry = kwargs.pop("industry")
        if not content and "page_content" in kwargs:
            content = kwargs.pop("page_content")
        if not sections_requested and "sections" in kwargs:
            sections_requested = kwargs.pop("sections")

        if not brand_name and not industry and not content:
            return {
                "status": "failed",
                "response": (
                    "Se requiere brand_name, industry o content "
                    "para generar una página web"
                ),
                "error": "brand_name, industry y content no proporcionados",
            }

        # Construir prompt de generación de página
        page_parts = [
            "Genera una página web completa con HTML5 y CSS3 integrados.",
            "Debe ser moderna, responsiva y profesional.",
            f"Tipo de página: {page_type}",
            f"Marca/Negocio: {brand_name or 'Sin especificar'}",
            f"Industria: {industry or 'General'}",
        ]

        if colors:
            primary = colors.get("primary", "#0066FF")
            secondary = colors.get("secondary", "#00D4AA")
            page_parts.append(
                f"Paleta de colores: primario={primary}, secundario={secondary}"
            )

        if content:
            page_parts.append(f"Contenido/servicios: {content}")

        if additional_context:
            page_parts.append(f"Contexto adicional: {additional_context}")

        # Secciones específicas solicitadas
        if sections_requested:
            page_parts.append(
                f"Secciones obligatorias: {', '.join(sections_requested)}"
            )
        else:
            page_parts.append(self._default_sections(page_type))

        page_parts.extend([
            "",
            "Requisitos de la página:",
            "- HTML5 semántico completo dentro de <html>...</html>",
            "- CSS3 integradas en etiqueta <style>",
            "- Diseño responsivo (mobile-first)",
            "- Header con navegación",
            "- Hero section con CTA prominente",
            "- Sección de beneficios/características",
            "- Sección de prueba social/testimonios",
            "- Sección de llamada a la acción final",
            "- Footer con info de contacto",
            "- Colores de marca aplicados consistentemente",
            "- Iconos con emojis donde sea apropiado",
            "- Animaciones CSS sutiles",
            "- Fuente moderna con @import @font-face",
            "- Output: SOLO el código HTML, sin markdown ni explicaciones",
        ])

        prompt = "\n".join(page_parts)

        try:
            llm = LLMClient()
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)
            html_content = self._extract_content(response)
            clean_html = self._clean_html_output(html_content)

            # Generar estructura estimada
            structure = self._infer_page_structure(page_type, sections_requested)

            return {
                "status": "success",
                "response": clean_html,
                "page_config": {
                    "page_type": page_type,
                    "brand_name": brand_name or "general",
                    "industry": industry or "general",
                    "has_responsive_design": True,
                    "has_animations": True,
                    "estimated_section_count": len(structure),
                },
                "structure": structure,
                "word_count": len(clean_html.split()),
                "html_size_bytes": len(clean_html.encode("utf-8")),
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error generando página web: {e}",
                "error": str(e),
            }

    def _default_sections(self, page_type: str) -> str:
        """
        Secciones por defecto según el tipo de página.
        """
        sections_map: dict[str, list[str]] = {
            "landing": ["hero", "benefits", "features", "testimonials", "pricing", "cta", "faq", "footer"],
            "landing_sales": ["hero", "problem", "solution", "features", "testimonials", "pricing", "guarantee", "cta", "faq", "footer"],
            "landing_product": ["hero", "product_showcase", "features", "specs", "testimonials", "pricing", "cta", "footer"],
            "corporate": ["hero", "about", "services", "team", "testimonials", "stats", "cta", "footer"],
            "portfolio": ["hero", "projects", "skills", "testimonials", "contact", "footer"],
            "coming_soon": ["hero", "countdown", "notify_form", "social_proof", "footer"],
            "newsletter": ["hero", "benefits", "examples", "signup", "social_proof", "footer"],
            "contact": ["hero", "contact_form", "info", "map", "faq", "footer"],
            "ecommerce": ["hero", "featured_products", "benefits", "categories", "testimonials", "cta", "footer"],
            "saaS": ["hero", "features", "demo", "pricing", "testimonials", "faq", "cta", "footer"],
            "restaurant": ["hero", "about", "menu", "gallery", "testimonials", "reservation", "contact", "footer"],
        }

        default_sections = [
            "hero", "info", "features", "testimonials", "cta", "footer"
        ]

        result = sections_map.get(page_type, default_sections)
        return f"Secciones sugeridas por defecto: {', '.join(result)}"

    def _infer_page_structure(
        self, page_type: str, sections_requested: list[str] | None
    ) -> list[dict]:
        """Inferir la estructura de la página a partir de los parámetros."""
        if sections_requested:
            return [
                {"id": i + 1, "section": s, "order": i + 1}
                for i, s in enumerate(sections_requested)
            ]

        structure_map: dict[str, list[str]] = {
            "landing": ["Hero", "Beneficios", "Características", "Testimonios", "Precios", "CTA", "FAQ", "Footer"],
            "corporate": ["Hero", "Sobre Nosotros", "Servicios", "Equipo", "Testimonios", "Estadísticas", "CTA", "Footer"],
            "portfolio": ["Hero", "Proyectos", "Habilidades", "Testimonios", "Contacto", "Footer"],
            "ecommerce": ["Hero", "Productos Destacados", "Beneficios", "Categorías", "Testimonios", "CTA", "Footer"],
            "saaS": ["Hero", "Características", "Demo", "Precios", "Testimonios", "FAQ", "CTA", "Footer"],
        }
        sections = structure_map.get(
            page_type, ["Hero", "Información", "Características", "Testimonios", "CTA", "Footer"]
        )

        return [
            {"id": i + 1, "section": s, "order": i + 1}
            for i, s in enumerate(sections)
        ]

    def _clean_html_output(self, content: str) -> str:
        """
        Limpiar el output HTML removiendo marcadores de markdown.
        """
        import re

        # Remover bloques markdown ```html ... ```
        cleaned = re.sub(r"^```(?:html)?\s*", "", content, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)

        # Remover etiquetas HTML envueltas en backticks
        cleaned = cleaned.replace("```", "")

        # Verificar que el HTML sea coherente
        cleaned = cleaned.strip()
        if not cleaned:
            return (
                "<!-- Generación de página web fallida. "
                "El LLM no pudo generar un HTML válido. -->"
            )

        return cleaned

    # =========================================================================
    # Fallback
    # =========================================================================

    def _default(
        self, params: dict, metadata: dict, tenant_id: str
    ) -> dict:
        """Fallback conversacional con LLM cuando no hay acción específica."""
        from ai_platform.orchestrator.llm_client import LLMClient

        message_text = params.get("message_text", "")
        if not message_text:
            message_text = params.get("params", {}).get("message_text", "")

        if not message_text:
            return {
                "status": "success",
                "response": (
                    "Soy el módulo de desarrollo web de AI Platform. "
                    "Puedo generar landing pages, sitios corporativos, "
                    "páginas de producto, portfolios, páginas de captura, "
                    "e-commerce y más. Todo con HTML y CSS responsivo. "
                    "¿Qué página necesitas?"
                ),
            }

        try:
            llm = LLMClient()
            prompt = (
                "Eres un experto diseñador y desarrollador web frontend. "
                "Genera código HTML y CSS moderno, responsivo y profesional. "
                f"Solicitud del usuario: {message_text}"
            )
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)
            content = self._extract_content(response)

            return {
                "status": "success",
                "response": content,
            }
        except Exception as e:
            logger.error(f"Error en default handler de ai-web: {e}", exc_info=True)
            return {
                "status": "success",
                "response": (
                    "No pude generar la página web en este momento. "
                    "¿Puedes especificar tipo de página, marca y contenido?"
                ),
            }

    def _extract_content(self, response: dict) -> str:
        """Extraer el contenido textual de la respuesta del LLM."""
        content = response.get("content", "") if isinstance(response, dict) else str(response)
        if content and content.strip():
            return content
        return "No se pudo generar la página. Intenta con parámetros más específicos."
