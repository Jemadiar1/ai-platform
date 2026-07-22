"""
Handler para el módulo ai-social.

Gestiona redes sociales con IA: creación de posts, análisis de engagement,
programación de contenido y respuestas automáticas.

Las acciones se dividen en:

- create_post: crear post optimizado para redes sociales
- analyze_engagement: analizar métricas de engagement
- default: fallback conversacional con LLM

"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Handler:
    """
    Handler para el módulo ai-social.

    GESTIONA REDES SOCIALES con IA.
    Incluye: análisis de engagement, programación de posts, auto-respuestas.

    Acciones soportadas:
        - create_post: Crear post para redes sociales
        - analyze_engagement: Analizar métricas de engagement
        - default: Fallback conversacional con LLM
    """

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar acción del módulo ai-social.

        Parámetros:
            payload: Dict con 'action' y parámetros de red social

        Retorna:
            Dict con status, response y metadata
        """
        action = payload.get("action", "default")
        params = payload.get("params", {})
        metadata = payload.get("metadata", {})
        tenant_id = metadata.get("tenant_id", params.get("tenant_id", "unknown"))

        logger.info(f"Ejecutando ai-social.{action} para tenant {tenant_id}")

        dispatch = {
            "create_post": self._create_post,
            "analyze_engagement": self._analyze_engagement,
            "default": self._default,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {
                "action": action,
                "status": "failed",
                "error": f"Acción '{action}' no encontrada en ai-social",
                "note": "Acciones disponibles: create_post, analyze_engagement, default",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            result = handler(params, metadata, tenant_id)
            result["action"] = action
            result["timestamp"] = datetime.utcnow().isoformat()
            return result
        except Exception as e:
            logger.error(f"Error ejecutando ai-social.{action}: {e}", exc_info=True)
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    # =========================================================================
    # Creación de posts
    # =========================================================================

    def _create_post(
        self, params: dict, metadata: dict, tenant_id: str
    ) -> dict:
        """Crear post optimizado para redes sociales con IA."""
        from ai_platform.orchestrator.llm_client import LLMClient

        platform = params.get("platform", "instagram")
        topic = params.get("topic", "")
        tone = params.get("tone", "profesional")
        language = params.get("language", "español")
        additional_context = params.get("context", "")
        kwargs = params.get("kwargs", {})

        # Determinar plataforma si viene en kwargs
        if not platform and "platform" in kwargs:
            platform = kwargs.pop("platform")

        # Construir tema a partir de kwargs si no hay topic
        if not topic and kwargs:
            topic = ", ".join(f"{k}: {v}" for k, v in kwargs.items())

        if not topic:
            return {
                "status": "failed",
                "response": "Se requiere un tema (topic) para crear un post",
                "error": "topic no proporcionado",
            }

        prompt_parts = [
            "Genera un post profesional y optimizado para redes sociales.",
            f"Plataforma: {platform}",
            f"Tema: {topic}",
            f"Tono: {tone}",
            f"Idioma: {language}",
        ]
        if additional_context:
            prompt_parts.append(f"Contexto adicional: {additional_context}")

        prompt_parts.extend(self._get_platform_guidelines(platform))

        prompt = "\n".join(prompt_parts)

        try:
            llm = LLMClient()
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)
            content = self._extract_content(response)

            return {
                "status": "success",
                "response": content,
                "platform": platform,
                "topic": topic,
                "tone": tone,
                "language": language,
                "suggested_media": self._suggest_media(platform),
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error creando post: {e}",
                "error": str(e),
            }

    def _get_platform_guidelines(self, platform: str) -> list[str]:
        """
        Construir instrucciones específicas según la plataforma.
        """
        guidelines: dict[str, list[str]] = {
            "instagram": [
                "-- Formato: Imagen con texto persuasivo.",
                "-- Incluir hook inicial impactante.",
                "-- Incluir 10-15 hashtags relevantes.",
                "-- Sugerir tipo de post: foto, carrusel, reel, stories.",
                "-- Extensión: 100-200 palabras de texto.",
            ],
            "facebook": [
                "-- Formato: Post textual con medio visual.",
                "-- Tono conversacional y cercano.",
                "-- Incluir CTA claro.",
                "-- Extensión: 200-500 palabras.",
            ],
            "linkedin": [
                "-- Formato: Post profesional tipo thought leadership.",
                "-- Incluye hook profesional, valor y reflexión.",
                "-- Extensión: 200-500 palabras.",
                "-- Incluir hashtags profesionales.",
            ],
            "tiktok": [
                "-- Formato: Guion corto para video.",
                "-- Hook en los primeros 3 segundos.",
                "-- Extensión: 50-150 palabras.",
                "-- Sugerir hashtags y tendencias.",
            ],
            "twitter": [
                "-- Formato: Thread o tweet único.",
                "-- Hook fuerte en el primer tweet.",
                "-- Cada tweet: max 280 caracteres.",
            ],
            "x": [
                "-- Formato: Tweet o thread.",
                "-- Hook fuerte, máximo impacto en pocas palabras.",
                "-- Extensión: 1-3 tweets como máximo.",
            ],
            "youtube": [
                "-- Formato: Descripción de video + ideas de título.",
                "-- Generar 5 variantes de título optimizado para CTR.",
                "-- Incluir hashtags y timestamps sugeridos.",
            ],
            "pinterest": [
                "-- Formato: Pin con descripción SEO.",
                "-- Generar título optimizado con keywords.",
                "-- Incluir descripción de 150-300 caracteres.",
            ],
        }

        guidelines["default"] = [
            "-- Formato: Post versátil multi-plataforma.",
            "-- Incluir texto, hashtags y CTA.",
            "-- Extensión: 100-300 palabras.",
        ]

        return guidelines.get(platform, guidelines["default"])

    def _suggest_media(self, platform: str) -> str:
        """Sugerir tipo de contenido visual según plataforma."""
        suggestions: dict[str, str] = {
            "instagram": "Foto de alta calidad, Carrusel Educativo, Reel de 15-30 seg, Stories",
            "facebook": "Imagen compartenble, Video corto, Link con preview",
            "linkedin": "Imagen profesional, Documento PDF, Video explicativo",
            "tiktok": "Video vertical 9:16, 15-60 seg, Audio viral",
            "twitter": "Imagen/infografía, Video corto, Hilo de imágenes",
            "youtube": "Miniatura con título llamativo, Video vertical o horizontal",
            "pinterest": "Imagen vertical 2:3, Infografía, Paso a paso",
        }
        return suggestions.get(platform, "Imagen o video de alta calidad")

    def _extract_content(self, response: dict) -> str:
        """Extraer el contenido textual de la respuesta del LLM."""
        content = response.get("content", "") if isinstance(response, dict) else str(response)
        if content and content.strip():
            return content
        return "No se pudo generar el post. Intenta con parámetros más específicos."

    # =========================================================================
    # Análisis de engagement
    # =========================================================================

    def _analyze_engagement(
        self, params: dict, metadata: dict, tenant_id: str
    ) -> dict:
        """Analizar métricas de engagement y generar insights con IA."""
        from ai_platform.orchestrator.llm_client import LLMClient

        platform = params.get("platform", "instagram")
        metrics = params.get("metrics", {})
        posts_data = params.get("posts", [])
        additional_context = params.get("context", "")
        kwargs = params.get("kwargs", {})

        if not metrics and not posts_data:
            return {
                "status": "failed",
                "response": "Se requieren métricas (metrics) o datos de posts para analizar engagement",
                "error": "metrics o posts no proporcionados",
            }

        # Construir prompt de análisis con datos de engagement
        analysis_parts = [
            "Analiza las métricas de engagement de redes sociales y proporciona "
            "insights accionables para mejorar el rendimiento.",
            f"Plataforma: {platform}",
        ]

        if metrics:
            analysis_parts.append("Métricas proporcionadas:")
            for key, value in metrics.items():
                analysis_parts.append(f"- {key}: {value}")

        if posts_data:
            analysis_parts.append("Datos de posts:")
            for post in posts_data[:10]:  # Máximo 10 posts
                post_str = ", ".join(f"{k}={v}" for k, v in post.items())
                analysis_parts.append(f"- {post_str}")

        if additional_context:
            analysis_parts.append(f"Contexto adicional: {additional_context}")

        analysis_parts.extend([
            "",
            "Por favor proporciona:",
            "1. Análisis de rendimiento general",
            "2. Identificación de patrones en posts de alto engagement",
            "3. Recomendaciones accionables para mejorar",
            "4. Sugerencias de contenido basado en lo que funciona",
            "5. Métricas benchmarks si es posible",
        ])

        prompt = "\n".join(analysis_parts)

        try:
            llm = LLMClient()
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)
            analysis = self._extract_content(response)

            # Calcular métricas derivadas
            derived_metrics = self._derive_metrics(metrics)

            return {
                "status": "success",
                "response": analysis,
                "platform": platform,
                "metrics_provided": derived_metrics,
                "post_analyzed_count": len(posts_data),
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error analizando engagement: {e}",
                "error": str(e),
            }

    def _derive_metrics(self, metrics: dict) -> dict:
        """Calcular métricas derivadas a partir de métricas base."""
        derived: dict[str, Any] = {}

        likes = 0
        comments = 0
        shares = 0
        reach = 0

        for key, value in metrics.items():
            if key in ("likes", "like_count", "reacciones"):
                likes = value
            elif key in ("comments", "comment_count", "comentarios"):
                comments = value
            elif key in ("shares", "share_count", "compartidos"):
                shares = value
            elif key in ("reach", "alcance", "impresiones"):
                reach = value

        total_interactions = likes + comments + shares
        if total_interactions > 0:
            derived["interacciones_totales"] = total_interactions
            if reach > 0:
                derived["tasa_engagement"] = round((total_interactions / reach) * 100, 2)
            else:
                derived["tasa_engagement"] = 0

        return derived

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
                    "Soy el módulo de redes sociales de AI Platform. "
                    "Puedo crear posts optimizados para Instagram, Facebook, LinkedIn, "
                    "TikTok, Twitter y YouTube. También analizo métricas de engagement. "
                    "¿Qué necesitas?"
                ),
            }

        try:
            llm = LLMClient()
            prompt = (
                "Eres un experto en gestión de redes sociales y marketing digital. "
                f"Responde a la siguiente solicitud:\n{message_text}"
            )
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)
            content = self._extract_content(response)

            return {
                "status": "success",
                "response": content,
            }
        except Exception as e:
            logger.error(f"Error en default handler de ai-social: {e}", exc_info=True)
            return {
                "status": "success",
                "response": (
                    "No pude procesar tu solicitud de redes sociales. "
                    "¿Puedes especificar plataforma, tema y objetivo?"
                ),
            }
