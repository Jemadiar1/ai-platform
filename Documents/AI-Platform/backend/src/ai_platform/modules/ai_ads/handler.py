"""
Handler para el módulo ai-ads.

Gestión de campañas publicitarias: generación de copy de anuncios,
optimización de campañas, y generación de audiencias objetivo.

Acciones disponibles:
- create_ad_copy: Generar copys para anuncios
- optimize_campaign: Analizar y sugerir mejoras de campaña
- generate_audience: Generar audiencias objetivo para campañas
"""

from typing import Any
import json
import logging
from datetime import datetime, timezone

from ai_platform.core.config import get_settings
from ai_platform.core.security import scanner

logger = logging.getLogger(__name__)


class Handler:
    """Handler para el módulo ai-ads."""
    
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar la acción de ads solicitada.
        
        Parámetros:
            payload: Datos de la tarea con "action" y parámetros
        
        Retorna:
            dict con el resultado de la ejecución
        """
        action = payload.get("action", "default")
        
        actions = {
            "create_ad_copy": self.create_ad_copy,
            "optimize_campaign": self.optimize_campaign,
            "generate_audience": self.generate_audience,
        }
        
        if action not in actions:
            logger.error(f"Acción no soportada en ai-ads: {action}")
            return {
                "action": action,
                "status": "error",
                "error": f"Acción no soportada en ai-ads: {action}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        logger.info(f"Ejecutando {action} en ai-ads")
        try:
            result = actions[action](payload)
            if isinstance(result, dict) and result.get("status") == "error":
                return {
                    "action": action,
                    "status": "error",
                    "result": result,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            logger.info(f"{action} completado")
            return {
                "action": action,
                "status": "success",
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(f"Error ejecutando {action} en ai-ads: {e}")
            return {
                "action": action,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    def create_ad_copy(self, payload: dict) -> dict:
        """
        Generar copys para anuncios publicitarios.
        
        Parámetros:
            payload: {
                "platform": "meta",
                "campaigngoal": "conversions",
                "product": "Software de CRM",
                "benefits": ["automatización", "reportes", "integraciones"],
                "target_audience": "directores de marketing",
                "language": "es",
                "variations": 5
            }
        
        Retorna:
            {"variations": [{"headline": "...", "body": "...", "cta": "..."}]}
        """
        platform = scanner.sanitize(payload.get("platform", "meta"))
        campaign_goal = scanner.sanitize(payload.get("campaigngoal", payload.get("campaign_goal", "conversions")))
        product = scanner.sanitize(payload.get("product", ""))
        benefits = payload.get("benefits", [])
        target_audience = scanner.sanitize(payload.get("target_audience", ""))
        language = scanner.sanitize(payload.get("language", "es"))
        variations = payload.get("variations", 5)
        budget_hint = scanner.sanitize(payload.get("budget_hint", ""))
        
        if not product:
            raise ValueError("Se requiere 'product' para generar copy de ads")
        
        logger.info(f"Generando {variations} variaciones de ads para: {product}")
        
        platform_configs = {
            "meta": {
                "max_headline": 40,
                "max_primary": 125,
                "max_description": 30,
                "formats": ["feed", "stories", "reels"]
            },
            "google": {
                "max_headline": 30,
                "max_desc": 90,
                "formats": ["search", "display", "shopping"]
            },
            "linkedin": {
                "max_headline": 70,
                "max_body": 2000,
                "formats": ["sponsored_content", "message_ads"]
            },
        }
        
        config = platform_configs.get(platform, platform_configs["meta"])
        
        try:
            s = get_settings()
            import httpx as httpx_mod
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
            
            system_prompt = (
                f"Eres un especialista en copywriting para publicidad digital.\n"
                f"Plataforma: {platform}\n"
                f"Meta de campaña: {campaign_goal}\n"
                f"Formatos: {', '.join(config.get('formats', []))}\n"
                f"Tamaño de headline máx: {config.get('max_headline', 40)} chars\n"
                f"Variaciones a generar: {variations}\n\n"
                f"Las variaciones deben usar diferentes:\n"
                f"- Ángulos de marketing (pago, social proof, urgencia, etc.)\n"
                f"- Estilos de headline\n"
                f"- Calls-to-action\n\n"
                f"Responde SIEMPRE en formato JSON:\n"
                '{"variations": [{"headline": "...", "primary_text": "...", "description": "...", '
                '"cta": "...", "angle": "...", "estimated_ctr": 0, "notes": "..."}], '
                '"best_practices": []}'
            )
            
            user_prompt = f"Producto: {product}"
            if benefits:
                user_prompt += f"\nBeneficios: {', '.join(benefits)}"
            if target_audience:
                user_prompt += f"\nPúblico objetivo: {target_audience}"
            if budget_hint:
                user_prompt += f"\nPresupuesto hint: {budget_hint}"
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.8,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en create_ad_copy: {e}")
                    result = {"variations": [], "best_practices": []}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            variations_result = result.get("variations", [])
            for v in variations_result:
                v.setdefault("estimated_ctr", round(1.5 + (len(variations_result) - 1) * 0.15, 2))
            
            logger.info(f"{len(variations_result)} variaciones de ads generadas")
            
            return {
                "variations": variations_result,
                "best_practices": result.get("best_practices", []),
                "platform": platform,
                "campaign_goal": campaign_goal,
                "total_variations": len(variations_result)
            }
        
        except Exception as e:
            logger.error(f"Error generando ad copy: {e}")
            return {
                "variations": [],
                "best_practices": [],
                "platform": platform,
                "error": str(e)
            }
    
    def optimize_campaign(self, payload: dict) -> dict:
        """
        Analizar campaña y sugerir optimizaciones.
        
        Parámetros:
            payload: {
                "campaign": {
                    "name": "Campaña Q2",
                    "platform": "meta",
                    "daily_budget": 100,
                    "metrics": {"impressions": 50000, "clicks": 1500, "conversions": 45}
                },
                "target_roas": 3.0,
                "language": "es"
            }
        
        Retorna:
            {"score": 65, "issues": [...], "recommendations": [...], "projected_impact": {...}}
        """
        campaign = payload.get("campaign", {})
        target_roas = payload.get("target_roas", 3.0)
        current_cpc = payload.get("current_cpc")
        current_ctr = payload.get("current_ctr")
        language = scanner.sanitize(payload.get("language", "es"))
        
        campaign_name = scanner.sanitize(campaign.get("name", "Sin nombre") if isinstance(campaign.get("name"), str) else "Sin nombre")
        platform = scanner.sanitize(campaign.get("platform", "meta") if isinstance(campaign.get("platform"), str) else "meta")
        daily_budget = campaign.get("daily_budget", 0)
        metrics = campaign.get("metrics", {})
        
        impressions = metrics.get("impressions", 0)
        clicks = metrics.get("clicks", 0)
        conversions = metrics.get("conversions", 0)
        spend = metrics.get("spend", 0)
        
        current_ctr = current_ctr or (clicks / impressions if impressions > 0 else 0)
        current_cpc = current_cpc or (spend / clicks if clicks > 0 else 0)
        current_roas = (conversions * 100) / spend if spend > 0 else 0
        
        logger.info(f"Optimizando campaña: {campaign_name}")
        
        try:
            s = get_settings()
            import httpx as httpx_mod
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
            
            system_prompt = (
                "Eres un especialista en optimización de campañas publicitarias.\n"
                f"Campaña: {campaign_name}\n"
                f"Plataforma: {platform}\n"
                f"ROAS objetivo: {target_roas}\n"
                f"Presupuesto diario: ${daily_budget}\n\n"
                "Analiza las métricas y proporciona recommendations accionables.\n"
                "Responde SIEMPRE en formato JSON:\n"
                '{"overall_score": 0, "issues": [{"severity": "high|medium|low", "description": "..."}], '
                '"recommendations": [{"action": "...", "impact": "high|medium|low", "effort": "low|medium|high", '
                '"expected_improvement": "..."}], '
                '"projected_impact": {"roas": 0, "ctr": 0, "cost_per_conversion": 0}}'
            )
            
            metrics_summary = (
                f"Impresiones: {impressions}\n"
                f"Clicks: {clicks}\n"
                f"Conversiones: {conversions}\n"
                f"Gasto: ${spend}\n"
                f"CTR actual: {current_ctr:.4f}\n"
                f"CPC actual: ${current_cpc:.4f}\n"
                f"ROAS actual: {current_roas:.2f}"
            )
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": metrics_summary},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en optimize_campaign: {e}")
                    result = {"overall_score": 0, "issues": [], "recommendations": [], "projected_impact": {}}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info("Optimización de campaña completada")
            
            return {
                "campaign_name": campaign_name,
                "platform": platform,
                **result
            }
        
        except Exception as e:
            logger.error(f"Error optimizando campaña: {e}")
            return {
                "campaign_name": campaign_name,
                "platform": platform,
                "overall_score": round(min(current_roas / max(target_roas, 0.01) * 50, 100), 1),
                "issues": [],
                "recommendations": [
                    "Revisar segmentación de audiencia",
                    "A/B testear creativos alternativos",
                    "Optimizar presupuesto por horario"
                ],
                "projected_impact": {},
                "error": str(e)
            }
    
    def generate_audience(self, payload: dict) -> dict:
        """
        Generar audiencias objetivo para campañas publicitarias.
        
        Parámetros:
            payload: {
                "product": "CRM enterprise",
                "industry": "tecnología",
                "language": "es"
            }
        
        Retorna:
            {"audiences": [{"name": "...", "description": "...", "interests": [...]}, ...]}
        """
        product = scanner.sanitize(payload.get("product", ""))
        industry = scanner.sanitize(payload.get("industry", ""))
        language = scanner.sanitize(payload.get("language", "es"))
        budget_range = scanner.sanitize(payload.get("budget_range", ""))
        
        if not product:
            raise ValueError("Se requiere 'product' para generar audiencias")
        
        logger.info(f"Generando audiencias para: {product}")
        
        try:
            s = get_settings()
            import httpx as httpx_mod
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
            
            system_prompt = (
                f"Eres un experto en definición de audiencias para publicidad digital.\n"
                f"Producto: {product}\n"
                f"Industria: {industry}\n\n"
                f"Generar audiencias detalladas con:\n"
                f"- Demográficos (edad, género, ubicación)\n"
                f"- Intereses y comportamientos\n"
                f"- Nivel de intención\n"
                f"- Tamaño estimado de audiencia\n"
                f"- Canales recomendados\n\n"
                f"Responde SIEMPRE en formato JSON:\n"
                '{"audiences": [{"name": "...", "size": "...", "interests": [], '
                '"demographics": {...}, "behaviors": [], '
                '"recommended_channels": [], "suggested_budget_allocation": 0}], '
                '"primary_audience": "...", "secondary_audience": "...", '
                '"exclusions": []}'
            )
            
            user_prompt = f"Producto/servicio: {product}"
            if industry:
                user_prompt += f"\nIndustria: {industry}"
            if budget_range:
                user_prompt += f"\nRango de presupuesto: {budget_range}"
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.7,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en generate_audience: {e}")
                    result = {"audiences": [], "primary_audience": "", "secondary_audience": "", "exclusions": []}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            audiences = result.get("audiences", [])
            logger.info(f"{len(audiences)} audiencias generadas")
            
            return {
                "audiences": audiences,
                "primary_audience": result.get("primary_audience", ""),
                "secondary_audience": result.get("secondary_audience", ""),
                "exclusions": result.get("exclusions", []),
                "product": product
            }
        
        except Exception as e:
            logger.error(f"Error generando audiencias: {e}")
            return {
                "audiences": [],
                "primary_audience": "",
                "secondary_audience": "",
                "exclusions": [],
                "product": product,
                "error": str(e)
            }
