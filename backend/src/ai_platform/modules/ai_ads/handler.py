"""
Handler para el módulo ai-ads.

Gestiona campañas publicitarias con IA: creación de campañas,
optimización de presupuesto, A/B testing y segmentación.

Las acciones se dividen en:

- create_campaign: crear campaña publicitaria con IA
- default: fallback conversacional con LLM

"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Handler:
    """
    Handler para el módulo ai-ads.

    GESTIONA CAMPAÑAS PUBLICITARIAS con IA.
    Incluye: creación de campañas, optimización de presupuesto, A/B testing.

    Acciones soportadas:
        - create_campaign: Crear campaña publicitaria
        - default: Fallback conversacional con LLM
    """

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar acción del módulo ai-ads.

        Parámetros:
            payload: Dict con 'action' y parámetros de campaña

        Retorna:
            Dict con status, response y metadata
        """
        action = payload.get("action", "default")
        params = payload.get("params", {})
        metadata = payload.get("metadata", {})
        tenant_id = metadata.get("tenant_id", params.get("tenant_id", "unknown"))

        logger.info(f"Ejecutando ai-ads.{action} para tenant {tenant_id}")

        dispatch = {
            "create_campaign": self._create_campaign,
            "default": self._default,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {
                "action": action,
                "status": "failed",
                "error": f"Acción '{action}' no encontrada en ai-ads",
                "note": "Acciones disponibles: create_campaign, default",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            result = handler(params, metadata, tenant_id)
            result["action"] = action
            result["timestamp"] = datetime.utcnow().isoformat()
            return result
        except Exception as e:
            logger.error(f"Error ejecutando ai-ads.{action}: {e}", exc_info=True)
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    # =========================================================================
    # Creación de campañas publicitarias
    # =========================================================================

    def _create_campaign(
        self, params: dict, metadata: dict, tenant_id: str
    ) -> dict:
        """Crear campaña publicitaria completa con IA."""
        from ai_platform.orchestrator.llm_client import LLMClient

        platform = params.get("platform", "meta")
        campaign_goal = params.get("campaign_goal", "conversions")
        budget = params.get("budget", 500)
        currency = params.get("currency", "USD")
        duration_days = params.get("duration_days", 30)
        keywords = params.get("keywords", [])
        target_audience = params.get("target_audience", "")
        industry = params.get("industry", "")
        tone = params.get("tone", "profesional")
        additional_context = params.get("context", "")
        kwargs = params.get("kwargs", {})

        # Extraer parámetros de kwargs si faltan
        if not platform and "platform" in kwargs:
            platform = kwargs.pop("platform")
        if not target_audience and "target_audience" in kwargs:
            target_audience = kwargs.pop("target_audience")
        if not industry and "industry" in kwargs:
            industry = kwargs.pop("industry")
        if not keywords and "keywords" in kwargs:
            keywords = kwargs.pop("keywords")

        if not keywords and not target_audience and not industry:
            return {
                "status": "failed",
                "response": (
                    "Se requiere keywords, target_audience o industry "
                    "para crear una campaña publicitaria"
                ),
                "error": "keywords, target_audience y industry no proporcionados",
            }

        # Construir prompt de campaña
        campaign_parts = [
            "Diseña una campaña publicitaria completa con IA. "
            "Incluye estrategia, copy, segmentación y presupuesto.",
            f"Plataforma: {platform}",
            f"Objetivo de campaña: {campaign_goal}",
            f"Presupuesto total: {budget} {currency}",
            f"Duración: {duration_days} días",
            f"Tono: {tone}",
        ]

        if keywords:
            campaign_parts.append(f"Keywords/temas: {', '.join(keywords)}")
        if target_audience:
            campaign_parts.append(f"Audiencia objetivo: {target_audience}")
        if industry:
            campaign_parts.append(f"Industria: {industry}")
        if additional_context:
            campaign_parts.append(f"Contexto adicional: {additional_context}")

        campaign_parts.extend([
            "",
            "Para cada variante de anuncio (genera 3 variantes A/B), incluye:",
            "- headline: Título del anuncio (max 40 chars)",
            "- body_text: Texto del cuerpo (max 125 chars)",
            "- cta_text: Texto del botón CTA",
            "- visual_suggestion: Descripción de imagen/video sugerido",
            "- audience_detail: Segmentación detallada recomendada",
            "- bid_strategy: Estrategia de puja sugerida",
            "",
            "Incluye recomendaciones de:",
            "- audiencia y segmentación",
            "- schedule de ejecución",
            "- budget allocation por fase",
            "- KPIs para medir el éxito",
            "- A/B test recommendations",
            "- Proyección de métricas basada en benchmarks de la plataforma",
        ])

        prompt = "\n".join(campaign_parts)

        try:
            llm = LLMClient()
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)
            content = self._extract_content(response)

            # Calcular métricas de la campaña
            daily_budget = round(budget / duration_days, 2) if duration_days > 0 else budget

            return {
                "status": "success",
                "response": content,
                "campaign_config": {
                    "platform": platform,
                    "goal": campaign_goal,
                    "total_budget": budget,
                    "currency": currency,
                    "daily_budget": daily_budget,
                    "duration_days": duration_days,
                    "tone": tone,
                    "variants": 3,
                },
                "projected_metrics": self._estimate_metrics(platform, campaign_goal, daily_budget),
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error creando campaña: {e}",
                "error": str(e),
            }

    def _estimate_metrics(
        self, platform: str, goal: str, daily_budget: float
    ) -> dict:
        """Estimar métricas basadas en benchmarks de la industria."""
        # Benchmarks aproximados por plataforma (CPC y CTR típicos)
        benchmarks: dict[str, dict[str, float]] = {
            "meta": {"cpc": 0.50, "ctr": 1.5, "cpm": 8.0},
            "facebook": {"cpc": 0.50, "ctr": 1.5, "cpm": 8.0},
            "instagram": {"cpc": 0.60, "ctr": 1.2, "cpm": 10.0},
            "google": {"cpc": 1.50, "ctr": 2.5, "cpm": 10.0},
            "google_ads": {"cpc": 1.50, "ctr": 2.5, "cpm": 10.0},
            "linkedin": {"cpc": 5.00, "ctr": 0.7, "cpm": 30.0},
            "tiktok": {"cpc": 0.40, "ctr": 2.0, "cpm": 6.0},
            "twitter": {"cpc": 0.30, "ctr": 1.0, "cpm": 5.0},
            "x": {"cpc": 0.30, "ctr": 1.0, "cpm": 5.0},
        }

        bench = benchmarks.get(platform, benchmarks["meta"])
        cpc = bench["cpc"]
        ctr = bench["ctr"] / 100

        impressions = int(daily_budget / bench["cpm"] * 1000) if bench["cpm"] > 0 else 0
        clicks = int(impressions * ctr)
        budget_pacing = self._estimate_budget_pacing(goal, daily_budget)

        return {
            "estimated_impressions": impressions,
            "estimated_clicks": clicks,
            "estimated_ctr": round(ctr * 100, 2),
            "estimated_cpc": round(cpc, 2),
            "budget_pacing_per_hour": round(daily_budget / 24, 2),
            "benchmarks_used": platform,
        }

    def _estimate_budget_pacing(self, goal: str, daily_budget: float) -> str:
        """Sugerir cómo distribuir el presupuesto a lo largo del día."""
        pacing_options: dict[str, str] = {
            "conversions": "Distribución agresiva en horas pico (10h-14h y 19h-22h)",
            "awareness": "Distribución uniforme a lo largo del día con picos en horas de mayor actividad",
            "traffic": "Distribución concentrada en horas laborales y fines de semana",
            "engagement": "Distribución enfocada en horas de mayor interacción social",
            "leads": "Distribución moderada con inversión en horas de mayor decisión de compra",
            "sales": "Distribución máxima en horas pico de compra, mínima en horas de menor actividad",
        }

        return pacing_options.get(
            goal, "Distribución uniforme con ajustes por rendimiento en tiempo real"
        )

    def _extract_content(self, response: dict) -> str:
        """Extraer el contenido textual de la respuesta del LLM."""
        content = response.get("content", "") if isinstance(response, dict) else str(response)
        if content and content.strip():
            return content
        return "No se pudo generar la campaña. Intenta con parámetros más específicos."

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
                    "Soy el módulo de publicidad de AI Platform. "
                    "Puedo crear campañas completas para Meta Ads (Facebook/Instagram), "
                    "Google Ads, TikTok Ads, LinkedIn Ads y Twitter Ads. "
                    "Incluyo copy A/B, segmentación, presupuesto y proyecciones. "
                    "¿Qué necesitas?"
                ),
            }

        try:
            llm = LLMClient()
            prompt = (
                "Eres un experto en publicidad digital y gestión de campañas "
                "de pago por clic. "
                f"Responde a la siguiente solicitud:\n{message_text}"
            )
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)
            content = self._extract_content(response)

            return {
                "status": "success",
                "response": content,
            }
        except Exception as e:
            logger.error(f"Error en default handler de ai-ads: {e}", exc_info=True)
            return {
                "status": "success",
                "response": (
                    "No pude procesar tu solicitud de campañas publicitarias. "
                    "¿Puedes especificar plataforma, objetivo y presupuesto?"
                ),
            }
