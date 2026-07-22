"""
Handler para el módulo ai-content.

Genera contenido de marketing con IA: blogs, emails, copy publicitario,
copy para redes sociales, y contenido genérico.

Las acciones se dividen en:

- generate_content: generar contenido específico según tipo y parámetros
- default: fallback conversacional con LLM

"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Handler:
    """
    Handler para el módulo ai-content.

    GENERA CONTENIDO DE MARKETING con IA.
    Incluye: posts para redes sociales, blogs, emails, copy publicitario.

    Acciones soportadas:
        - generate_content: Generar contenido de marketing con IA
        - default: Fallback conversacional con LLM
    """

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar acción del módulo ai-content.

        Parámetros:
            payload: Dict con 'action' y parámetros de contenido

        Retorna:
            Dict con status, response y metadata
        """
        action = payload.get("action", "default")
        params = payload.get("params", {})
        metadata = payload.get("metadata", {})
        tenant_id = metadata.get("tenant_id", params.get("tenant_id", "unknown"))

        logger.info(f"Ejecutando ai-content.{action} para tenant {tenant_id}")

        dispatch = {
            "generate_content": self._generate_content,
            "default": self._default,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {
                "action": action,
                "status": "failed",
                "error": f"Acción '{action}' no encontrada en ai-content",
                "note": "Acciones disponibles: generate_content, default",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            result = handler(params, metadata, tenant_id)
            result["action"] = action
            result["timestamp"] = datetime.utcnow().isoformat()
            return result
        except Exception as e:
            logger.error(f"Error ejecutando ai-content.{action}: {e}", exc_info=True)
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    # =========================================================================
    # Generación de contenido
    # =========================================================================

    def _generate_content(
        self, params: dict, metadata: dict, tenant_id: str
    ) -> dict:
        """Generar contenido de marketing con IA según tipo, tema y tono."""
        from ai_platform.orchestrator.llm_client import LLMClient

        content_type = params.get("content_type", "blog")
        topic = params.get("topic", "")
        tone = params.get("tone", "profesional")
        language = params.get("language", "español")
        additional_context = params.get("context", "")
        kwargs = params.get("kwargs", {})

        if not topic:
            # Si hay kwargs, tratarlos como contenido temático
            if kwargs:
                topic = ", ".join(f"{k}: {v}" for k, v in kwargs.items())
            else:
                return {
                    "status": "failed",
                    "response": "Se requiere un tema (topic) para generar contenido",
                    "error": "topic no proporcionado",
                }

        prompt_parts = [
            "Genera contenido de marketing profesional y persuasivo.",
            f"Tipo de contenido: {content_type}",
            f"Tema: {topic}",
            f"Tono: {tone}",
            f"Idioma del output: {language}",
        ]
        if additional_context:
            prompt_parts.append(f"Contexto adicional: {additional_context}")

        # Construir guía para el tipo de contenido específico
        prompt_parts.extend(self._build_content_guide(content_type, topic, tone))

        prompt = "\n".join(prompt_parts)

        try:
            llm = LLMClient()
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)

            content = self._extract_content(response)

            return {
                "status": "success",
                "response": content,
                "content_type": content_type,
                "topic": topic,
                "tone": tone,
                "language": language,
                "word_count": len(content.split()),
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error generando contenido: {e}",
                "error": str(e),
            }

    def _build_content_guide(
        self, content_type: str, topic: str, tone: str
    ) -> list[str]:
        """
        Construir instrucciones específicas según el tipo de contenido.
        """
        guides: dict[str, list[str]] = {
            "blog": [
                "Estructura: título atractivo, introducción con hook, "
                "3-5 secciones con subtítulos H2, conclusión con CTA.",
                "Extensión sugerida: 600-1200 palabras.",
                "Incluir keywords de forma natural.",
            ],
            "email": [
                "Estructura: subject line atractivo, saludo personalizado, "
                "cuerpo con valor claro, CTA prominente, firma profesional.",
                "Extensión sugerida: 150-300 palabras.",
                "Incluir 1-2 variantes de subject line.",
            ],
            "instagram": [
                "Genera un post visual con texto persuasivo.",
                "Incluir: hook inicial, cuerpo del post, CTA, y 10-15 hashtags relevantes.",
                "Extensión sugerida: 100-200 palabras.",
            ],
            "facebook": [
                "Genera un post para Facebook con tono conversacional.",
                "Incluir: texto principal (max 2000 caracteres), hashtags, y CTA.",
                "Sugerir tipo de media apropiada (imagen, video, carrusel).",
            ],
            "linkedin": [
                "Genera un post profesional para LinkedIn.",
                "Incluir: hook profesional, insights de valor, CTA a reflexión o acción.",
                "Extensión sugerida: 200-600 palabras.",
                "Incluir hashtags profesionales.",
            ],
            " TikTok": [
                "Genera un guion para TikTok/Shorts.",
                "Estructura: hook inicial (3 seg), contenido principal, CTA a seguir.",
                "Extensión sugerida: 50-150 palabras (30-60 seg de video).",
                "Incluir sugerencias de hashtags y audio.",
            ],
            "twitter": [
                "Genera un thread de Twitter/X.",
                "Estructura: tweet hook (hilo), 3-5 tweets de valor, tweet final con CTA.",
                "Cada tweet: max 280 caracteres.",
            ],
            "ad_copy": [
                "Genera copy publicitario persuasivo.",
                "Incluir: headline impactante, descripción, texto de CTA.",
                "Generar 3 variantes A/B.",
                "Incluir hashtags y sugerencia de segmentación.",
            ],
            "seo": [
                "Genera contenido optimizado para SEO.",
                "Incluir: meta title (max 60 chars), meta description (max 160 chars), "
                "keywords principales y secundarias, estructura de headings.",
                "Extensión sugerida: 800-1500 palabras.",
            ],
        }

        guides["default"] = [
            "Genera contenido de marketing original y atractivo.",
            "Extensión sugerida: 200-500 palabras.",
        ]
        guides["generico"] = guides["default"]

        guide = guides.get(content_type, guides["default"])
        if not isinstance(guide, list):
            guide = ["Genera contenido de marketing de calidad."]

        return guide

    def _extract_content(self, response: dict) -> str:
        """Extraer el contenido textual de la respuesta del LLM."""
        content = response.get("content", "") if isinstance(response, dict) else str(response)
        if content and content.strip():
            return content
        return "No se pudo generar contenido. Intenta con parámetros más específicos."

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
                    "Soy el módulo de contenido de AI Platform. "
                    "Puedo generar: blogs, emails, posts para Instagram/Facebook/LinkedIn/TikTok/Twitter, "
                    "copy publicitario, y contenido SEO. ¿Qué necesites?"
                ),
            }

        try:
            llm = LLMClient()
            prompt = (
                "Eres un experto en marketing digital de contenido. "
                f"Responde a la siguiente solicitud:\n{message_text}"
            )
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)
            content = self._extract_content(response)

            return {
                "status": "success",
                "response": content,
            }
        except Exception as e:
            logger.error(f"Error en default handler de ai-content: {e}", exc_info=True)
            return {
                "status": "success",
                "response": (
                    "No pude generar contenido en este momento. "
                    "¿Puedes especificar tipo de contenido, tema y tono?"
                ),
            }
