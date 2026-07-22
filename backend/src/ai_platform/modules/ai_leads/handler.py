"""
Handler para el módulo ai-leads.

Captura y califica leads con IA: generación de leads calificados,
scoring, enriquecimiento de datos y routing a ventas.

Las acciones se dividen en:

- generate_leads: generación de leads calificados con IA
- default: fallback conversacional con LLM

"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Handler:
    """
    Handler para el módulo ai-leads.

    CAPTURA Y CALIFICA LEADS con IA.
    Incluye: scoring de leads, enriquecimiento de datos, routing.

    Acciones soportadas:
        - generate_leads: Generar leads calificados con IA
        - default: Fallback conversacional con LLM
    """

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar acción del módulo ai-leads.

        Parámetros:
            payload: Dict con 'action' y parámetros de lead

        Retorna:
            Dict con status, response y metadata
        """
        action = payload.get("action", "default")
        params = payload.get("params", {})
        metadata = payload.get("metadata", {})
        tenant_id = metadata.get("tenant_id", params.get("tenant_id", "unknown"))

        logger.info(f"Ejecutando ai-leads.{action} para tenant {tenant_id}")

        dispatch = {
            "generate_leads": self._generate_leads,
            "default": self._default,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {
                "action": action,
                "status": "failed",
                "error": f"Acción '{action}' no encontrada en ai-leads",
                "note": "Acciones disponibles: generate_leads, default",
                "timestamp": datetime.utcnow().isoformat(),
            }

        try:
            result = handler(params, metadata, tenant_id)
            result["action"] = action
            result["timestamp"] = datetime.utcnow().isoformat()
            return result
        except Exception as e:
            logger.error(f"Error ejecutando ai-leads.{action}: {e}", exc_info=True)
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    # =========================================================================
    # Generación de leads
    # =========================================================================

    def _generate_leads(
        self, params: dict, metadata: dict, tenant_id: str
    ) -> dict:
        """Generar leads calificados con IA según industria y target."""
        from ai_platform.orchestrator.llm_client import LLMClient

        industry = params.get("industry", "")
        target_audience = params.get("target_audience", "")
        num_leads = params.get("num_leads", 5)
        lead_score_threshold = params.get("lead_score_threshold", 60)
        keywords = params.get("keywords", [])
        additional_context = params.get("context", "")
        kwargs = params.get("kwargs", {})

        # Extraer parámetros de kwargs si no se proporcionaron en params
        if not industry and "industry" in kwargs:
            industry = kwargs.pop("industry")
        if not target_audience and "target_audience" in kwargs:
            target_audience = kwargs.pop("target_audience")
        if not keywords and "keywords" in kwargs:
            keywords = kwargs.pop("keywords")

        if not industry and not target_audience:
            return {
                "status": "failed",
                "response": "Se requiere industria (industry) o audiencia objetivo (target_audience) para generar leads",
                "error": "industry y target_audience no proporcionados",
            }

        # Construir prompt de generación de leads
        lead_parts = [
            "Genera un listado de leads calificados con IA. Cada lead debe tener "
            "datos realistas y accionables para equipos de ventas.",
            f"Industria: {industry}",
            f"Audiencia objetivo: {target_audience}",
            f"Cantidad de leads: {num_leads}",
            f"Puntuación mínima de lead (1-100): {lead_score_threshold}",
        ]

        if keywords:
            lead_parts.append(f"Keywords relevantes: {', '.join(keywords)}")

        if additional_context:
            lead_parts.append(f"Contexto adicional: {additional_context}")

        lead_parts.extend([
            "",
            "Para cada lead, proporciona en JSON:",
            "- nombre: Nombre completo del contacto",
            "- email: Correo electrónico",
            "- teléfono: Número de teléfono",
            "- empresa: Nombre de empresa",
            "- cargo: Puesto o cargo",
            "- industria: Industria de la empresa",
            "- ciudad: Ciudad",
            "-lead_score: Puntuación calificación (1-100)",
            "- motivación: Motivación de compra identificada",
            "- presupuesto_est: Rango de presupuesto estimado",
            "- nivel_interés: Alto / Medio / Bajo",
            "- canal_recomendado: Canal óptimo para contactar",
            "- nota: Observación breve para el equipo de ventas",
            "",
            "Incluye solo leads con score >= umbral.",
            "Prioriza leads con mayor probabilidad de conversión.",
        ])

        prompt = "\n".join(lead_parts)

        try:
            llm = LLMClient()
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)

            # Parsear la respuesta del LLM como JSON de leads
            leads = self._parse_leads_response(response)

            # Calcular estadísticas de leads generados
            stats = self._calculate_lead_stats(leads, lead_score_threshold)

            return {
                "status": "success",
                "response": self._format_lead_summary(leads),
                "leads": leads,
                "total_generated": len(leads),
                "statistics": stats,
                "industry": industry or "general",
                "target_audience": target_audience or "general",
            }
        except Exception as e:
            return {
                "status": "failed",
                "response": f"Error generando leads: {e}",
                "error": str(e),
            }

    def _parse_leads_response(self, response: dict) -> list[dict]:
        """
        Parsear la respuesta del LLM para extraer leads.

        Intenta múltiples formatos de respuesta JSON.
        """
        leads: list[dict] = []

        try:
            content = response.get("content", "") if isinstance(response, dict) else str(response)
            if not content or not content.strip():
                return leads

            import json

            # Intentar parsear como lista JSON directamente
            content_stripped = content.strip()

            # Intentar con lista [ {...}, {...} ]
            try:
                leads = json.loads(content_stripped)
                if isinstance(leads, list):
                    return self._validate_leads(leads)
            except json.JSONDecodeError:
                pass

            # Intentar con diccionario con clave "leads"
            try:
                data = json.loads(content_stripped)
                if isinstance(data, dict):
                    if "leads" in data:
                        return self._validate_leads(data["leads"])
                    if "data" in data:
                        return self._validate_leads(data["data"])
            except json.JSONDecodeError:
                pass

            # Intentar encontrar JSON en texto (entre ```json y ```)
            if "```" in content:
                import re
                json_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", content)
                if json_blocks:
                    for block in json_blocks:
                        try:
                            leads = json.loads(block)
                            if isinstance(leads, list):
                                return self._validate_leads(leads)
                        except json.JSONDecodeError:
                            continue

            # Fallback: intentar parsear el bloque JSON más grande
            try:
                # Buscar el primer { y el último }
                start = content_stripped.find("{")
                end = content_stripped.rfind("}")
                if start >= 0 and end > start:
                    json_str = content_stripped[start : end + 1]
                    data = json.loads(json_str)
                    if isinstance(data, list):
                        return self._validate_leads(data)
                    if isinstance(data, dict) and "leads" in data:
                        return self._validate_leads(data["leads"])
            except json.JSONDecodeError:
                pass

        except Exception:
            pass

        return leads

    def _validate_leads(self, leads: list) -> list[dict]:
        """Validar y normalizar estructura de leads."""
        validated: list[dict] = []
        for lead in leads:
            if isinstance(lead, dict):
                validated.append({
                    "nombre": lead.get("nombre", lead.get("name", "Contacto")),
                    "email": lead.get("email", lead.get("correo", "N/A")),
                    "teléfono": lead.get("teléfono", lead.get("phone", "N/A")),
                    "empresa": lead.get("empresa", lead.get("company", "N/A")),
                    "cargo": lead.get("cargo", lead.get("position", "N/A")),
                    "lead_score": lead.get("lead_score", lead.get("score", 50)),
                    "nivel_interés": lead.get("nivel_interés", lead.get("interest_level", "Medio")),
                    "canal_recomendado": lead.get("canal_recomendado", lead.get("channel", "email")),
                })
        return validated

    def _calculate_lead_stats(
        self, leads: list[dict], threshold: int
    ) -> dict:
        """Calcular estadísticas sobre los leads generados."""
        if not leads:
            return {
                "total": 0,
                "high_score_count": 0,
                "avg_score": 0,
                "high_interest_count": 0,
            }

        scores = []
        high_interest = 0

        for lead in leads:
            score = lead.get("lead_score", 0)
            scores.append(score)
            nivel = str(lead.get("nivel_interés", "")).lower()
            if "alto" in nivel:
                high_interest += 1

        return {
            "total": len(leads),
            "high_score_count": sum(1 for s in scores if s >= threshold),
            "avg_score": round(sum(scores) / len(scores), 1),
            "min_score": min(scores),
            "max_score": max(scores),
            "high_interest_count": high_interest,
            "high_interest_pct": round((high_interest / len(leads)) * 100, 1),
        }

    def _format_lead_summary(self, leads: list[dict]) -> str:
        """Generar resumen legible de los leads para el response principal."""
        if not leads:
            return "No se generaron leads."

        lines = [f"Se generaron {len(leads)} leads calificados:\n"]

        for i, lead in enumerate(leads, 1):
            score = lead.get("lead_score", "N/A")
            nivel = lead.get("nivel_interés", "N/A")
            name = lead.get("nombre", "Contacto")
            company = lead.get("empresa", "N/A")
            email = lead.get("email", "N/A")
            channel = lead.get("canal_recomendado", "N/A")

            lines.append(
                f"{i}. {name} — {company} | "
                f"score: {score}/100 | interés: {nivel} | "
                f"email: {email} | canal: {channel}"
            )

        return "\n".join(lines)

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
                    "Soy el módulo de leads de AI Platform. "
                    "Puedo generar leads calificados con perfiles completos, "
                    "puntuar leads existentes, enriquecer datos de contactos "
                    "y recomendar el mejor canal de contacto. ¿Qué necesitas?"
                ),
            }

        try:
            llm = LLMClient()
            prompt = (
                "Eres un experto en generación y gestión de leads B2B/B2C. "
                f"Responde a la siguiente solicitud:\n{message_text}"
            )
            response = llm.chat(prompt=prompt, tenant_id=tenant_id)
            content = self._extract_content(response)

            return {
                "status": "success",
                "response": content,
            }
        except Exception as e:
            logger.error(f"Error en default handler de ai-leads: {e}", exc_info=True)
            return {
                "status": "success",
                "response": (
                    "No pude generar leads en este momento. "
                    "¿Puedes especificar industria, audiencia objetivo y cantidad?"
                ),
            }

    def _extract_content(self, response: dict) -> str:
        """Extraer el contenido textual de la respuesta del LLM."""
        content = response.get("content", "") if isinstance(response, dict) else str(response)
        if content and content.strip():
            return content
        return "No se pudo procesar la solicitud. Intenta con más detalles."
