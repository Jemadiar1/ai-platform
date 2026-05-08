"""
Handler para el módulo ai-web.

Generación de landing pages, copys de sitios web,
y análisis de presencia web.

Acciones disponibles:
- generate_landing: Crear landing page completa con HTML
- generate_copy: Generar texto para secciones del sitio
- analyze_site: Analizar y sugerir mejoras del sitio web actual
"""

from typing import Any
import json
import logging
from datetime import datetime, timezone

from ai_platform.core.config import get_settings
from ai_platform.core.security import scanner

logger = logging.getLogger(__name__)


class Handler:
    """Handler para el módulo ai-web."""
    
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar la acción de generación web solicitada.
        
        Parámetros:
            payload: Datos de la tarea con "action" y parámetros
        
        Retorna:
            dict con el resultado de la ejecución
        """
        action = payload.get("action", "default")
        
        actions = {
            "generate_landing": self.generate_landing,
            "generate_copy": self.generate_copy,
            "analyze_site": self.analyze_site,
        }
        
        if action not in actions:
            logger.error(f"Acción no soportada en ai-web: {action}")
            return {
                "action": action,
                "status": "error",
                "error": f"Acción no soportada en ai-web: {action}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        logger.info(f"Ejecutando {action} en ai-web")
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
            logger.error(f"Error ejecutando {action} en ai-web: {e}")
            return {
                "action": action,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    def generate_landing(self, payload: dict) -> dict:
        """
        Generar landing page completa en HTML.
        
        Parámetros:
            payload: {
                "business_name": "Mi Empresa",
                "product": "Software de CRM",
                "industry": "Tecnología",
                "style": "moderno y minimalista",
                "color_scheme": "azul y blanco",
                "cta_text": "Comienza gratis",
                "language": "es"
            }
        
        Retorna:
            {"html": "...", "sections": [...], "seo_metadata": {...}}
        """
        business_name = scanner.sanitize(payload.get("business_name", ""))
        product = scanner.sanitize(payload.get("product", ""))
        industry = scanner.sanitize(payload.get("industry", ""))
        style = scanner.sanitize(payload.get("style", "moderno"))
        color_scheme = scanner.sanitize(payload.get("color_scheme", "azul y blanco"))
        cta_text = scanner.sanitize(payload.get("cta_text", "Comienza ahora"))
        language = scanner.sanitize(payload.get("language", "es"))
        target_audience = scanner.sanitize(payload.get("target_audience", "") or "")
        key_benefits = payload.get("key_benefits", [])
        
        if not product:
            raise ValueError("Se requiere 'product' para generar landing page")
        
        logger.info(f"Generando landing page para: {product}")
        
        try:
            s = get_settings()
            import httpx as httpx_mod
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=60.0
            )
            
            system_prompt = (
                f"Eres un desarrollador web y copywriter experto.\n"
                f"Genera una landing page completa en HTML con CSS inline.\n"
                f"Estilo: {style}\n"
                f"Esquema de colores: {color_scheme}\n"
                f"Texto del CTA: {cta_text}\n"
                f"Idioma: {language}\n\n"
                f"La landing debe incluir:\n"
                f"1. Hero section con headline y subtítulo\n"
                f"2. Sección de beneficios/features\n"
                f"3. Social proof / testimonios\n"
                f"4. CTA section\n"
                f"5. Footer\n\n"
                f"Responde en formato JSON:\n"
                '{"html": "<!DOCTYPE html>...", "sections": ["hero", "benefits", ...], "seo_metadata": {}}'
            )
            
            user_prompt = f"Negocio: {business_name}\nProducto: {product}\nIndustria: {industry}"
            if target_audience:
                user_prompt += f"\nPúblico objetivo: {target_audience}"
            if key_benefits:
                user_prompt += f"\nBeneficios clave: {', '.join(key_benefits)}"
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 8192,
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
                    logger.error(f"JSON inválido de LLM en generate_landing: {e}")
                    result = {"html": "", "sections": ["hero", "features", "cta", "footer"], "seo_metadata": {}}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info(f"Landing page generada para {business_name or product}")
            
            return {
                "html": result.get("html", ""),
                "sections": result.get("sections", ["hero", "features", "cta", "footer"]),
                "seo_metadata": result.get("seo_metadata", {}),
                "business_name": business_name,
                "product": product,
                "style": style
            }
        
        except Exception as e:
            logger.error(f"Error generando landing page: {e}")
            return {
                "html": "",
                "sections": [],
                "seo_metadata": {},
                "product": product,
                "error": str(e)
            }
    
    def generate_copy(self, payload: dict) -> dict:
        """
        Generar copys para secciones específicas del sitio web.
        
        Parámetros:
            payload: {
                "section": "hero",
                "product": "CRM inteligente",
                "tone": "profesional",
                "language": "es"
            }
        
        Retorna:
            {"headline": "...", "subheadline": "...", "body": "...", "cta": "..."}
        """
        section = scanner.sanitize(payload.get("section", "hero"))
        product = scanner.sanitize(payload.get("product", ""))
        tone = scanner.sanitize(payload.get("tone", "profesional"))
        language = scanner.sanitize(payload.get("language", "es"))
        key_points = payload.get("key_points", [])
        
        if not product:
            raise ValueError("Se requiere 'product' para generar copy web")
        
        logger.info(f"Generando copy para sección '{section}' de: {product}")
        
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
            
            section_prompts = {
                "hero": {
                    "prompt": "Eres un web copywriter. Genera un headline poderoso, subheadline persuasivo, y texto del CTA para la sección hero de un sitio web.",
                    "format": '{"headline": "...", "subheadline": "...", "cta_text": "...", "description": "..."}'
                },
                "about": {
                    "prompt": "Genera el texto para la sección 'Sobre nosotros' del sitio web.",
                    "format": '{"title": "...", "short_description": "...", "long_description": "...", "values": []}'
                },
                "features": {
                    "prompt": "Genera los textos para la sección de features/beneficios del sitio web.",
                    "format": '{"title": "...", "features": [{"icon": "...", "title": "...", "description": "..."}]}'
                },
                "testimonials": {
                    "prompt": "Genera testimonios realistas para la sección de social proof.",
                    "format": '{"title": "...", "testimonials": [{"name": "...", "role": "...", "text": "..."}]}'
                },
                "pricing": {
                    "prompt": "Genera textos para la sección de precios con planes diferenciados.",
                    "format": '{"title": "...", "tagline": "...", "plans": [{"name": "...", "price": "...", "features": []}]}'
                },
            }
            
            section_config = section_prompts.get(section, section_prompts["hero"])
            
            system_prompt = f"{section_config['prompt']}\nTono: {tone}\nIdioma: {language}\n\nResponde SIEMPRE en formato JSON:\n{section_config['format']}"
            
            user_prompt = f"Producto/servicio: {product}"
            if key_points:
                user_prompt += f"\nPuntos clave: {', '.join(key_points)}"
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 2048,
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
                    logger.error(f"JSON inválido de LLM en generate_copy (web): {e}")
                    result = {"headline": product, "subheadline": "", "cta_text": "Contactar", "description": ""}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info(f"Copy generado para sección '{section}'")
            
            return {
                "section": section,
                "product": product,
                **result
            }
        
        except Exception as e:
            logger.error(f"Error generando copy: {e}")
            return {
                "section": section,
                "product": product,
                "headline": product,
                "subheadline": "",
                "cta_text": "Contactar",
                "error": str(e)
            }
    
    def analyze_site(self, payload: dict) -> dict:
        """
        Analizar presencia web y sugerir mejoras.
        
        Parámetros:
            payload: {
                "url": "https://miempresa.com",
                "content": "HTML del sitio web actual",
                "focus_areas": ["seo", "conversion", "copy"]
            }
        
        Retorna:
            {"score": 75, "issues": [...], "suggestions": [...], "category": "..."}
        """
        url = scanner.sanitize(payload.get("url", ""))
        site_content = scanner.sanitize(payload.get("content", ""))
        focus_areas = payload.get("focus_areas", ["seo", "conversion", "copy"])
        
        logger.info(f"Analizando sitio web: {url or 'no URL proporcionada'}")
        
        try:
            s = get_settings()
            import httpx as httpx_mod
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=60.0
            )
            
            system_prompt = (
                "Eres un experto en UX, SEO y optimización de conversión de sitios web.\n"
                "Analiza el contenido del sitio y proporciona un análisis detallado.\n"
                "Áreas de enfoque: {focus_areas}\n\n"
                "Responde SIEMPRE en formato JSON:\n"
                '{"overall_score": 0, "seo_score": 0, "conversion_score": 0, '
                '"ux_score": 0, "issues": [], "suggestions": []}'
            )
            
            user_prompt = f"URL: {url}\n\nContenido del sitio:\n{site_content}"
            if not site_content:
                user_prompt = f"URL: {url}\n\nPor favor, analiza este sitio web y sugiere mejoras."
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.5,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en analyze_site: {e}")
                    result = {"overall_score": 0, "seo_score": 0, "conversion_score": 0, "ux_score": 0, "issues": [], "suggestions": []}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info("Análisis de sitio web completado")
            
            return {
                "url": url,
                "focus_areas": focus_areas,
                **result
            }
        
        except Exception as e:
            logger.error(f"Error analizando sitio: {e}")
            return {
                "url": url,
                "focus_areas": focus_areas,
                "overall_score": 0,
                "seo_score": 0,
                "conversion_score": 0,
                "ux_score": 0,
                "issues": [],
                "suggestions": [],
                "error": str(e)
            }
