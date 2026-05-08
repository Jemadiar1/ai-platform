"""
Handler para el módulo ai-content.

Generación de contenido con IA: artículos, copys publicitarios,
reescritura de contenido, y más.

Usa OpenRouter para acceder a modelos LLM (Claude, GPT-4, etc.)
y generar contenido de alta calidad en español e inglés.

Acciones disponibles:
- generate_article: Generar artículos de blog completos
- generate_copy: Generar copys para redes sociales o landing pages
- rewrite_content: Reescribir contenido existente con diferente tono
"""

from typing import Any
import json
import logging
from datetime import datetime, timezone

from ai_platform.orchestrator.llm_client import LLMClient
from ai_platform.core.security import scanner

logger = logging.getLogger(__name__)


class Handler:
    """Handler para el módulo ai-content."""
    
    def __init__(self):
        self.llm_client = LLMClient()
    
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar la acción de generación de contenido solicitada.
        
        Parámetros:
            payload: Datos de la tarea con "action" y parámetros
        
        Retorna:
            dict con el resultado de la generación
        """
        action = payload.get("action", "default")
        
        actions = {
            "generate_article": self.generate_article,
            "generate_copy": self.generate_copy,
            "rewrite_content": self.rewrite_content,
        }
        
        if action not in actions:
            logger.error(f"Acción no soportada en ai-content: {action}")
            return {
                "action": action,
                "status": "error",
                "error": f"Acción no soportada en ai-content: {action}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        logger.info(f"Ejecutando {action} en ai-content")
        try:
            result = actions[action](payload)
            # Propagar el estado de error si el método interno lo reporta
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
            logger.error(f"Error ejecutando {action} en ai-content: {e}")
            return {
                "action": action,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    def generate_article(self, payload: dict) -> dict:
        """
        Generar un artículo de blog completo.
        
        Parámetros:
            payload: {
                "topic": "Inteligencia Artificial en marketing",
                "tone": "profesional",
                "language": "es",
                "word_count": 1500,
                "keywords": ["IA", "marketing", "automatización"]
            }
        
        Retorna:
            {
                "title": "...",
                "content": "...",
                "meta_description": "...",
                "word_count": 1500,
                "keywords": [...]
            }
        """
        topic = scanner.sanitize(payload.get("topic", ""))
        tone = scanner.sanitize(payload.get("tone", "profesional"))
        language = scanner.sanitize(payload.get("language", "es"))
        word_count = payload.get("word_count", 1500)
        keywords = payload.get("keywords", [])
        outline = scanner.sanitize(payload.get("outline", "") or "")
        tenant_id = payload.get("tenant_id")
        
        if not topic:
            raise ValueError("Se requiere 'topic' para generar artículo")
        
        logger.info(f"Generando artículo sobre: {topic}")
        
        try:
            system_prompt = (
                f"Eres un redactor profesional especializado en contenido de calidad.\n"
                f"Tono: {tone}\n"
                f"Idioma: {language}\n"
                f"Palabras objetivo: {word_count}\n\n"
                f"Genera un artículo completo con:\n"
                f"1. Título atractivo (h1)\n"
                f"2. Meta descripción (máx 160 caracteres)\n"
                f"3. Introducción con hook\n"
                f"4. Cuerpo con subtítulos (h2, h3)\n"
                f"5. Conclusión con call-to-action\n"
                f"6. Palabras clave sugeridas\n\n"
                f"Responde SIEMPRE en formato JSON:\n"
                f'{{"title": "...", "meta_description": "...", "content": "...", "word_count": 0, "keywords": [], "suggested_tags": []}}'
            )
            
            user_prompt = f"Tema: {topic}"
            if keywords:
                user_prompt += f"\nPalabras clave: {', '.join(keywords)}"
            if outline:
                user_prompt += f"\nEsquema requerido:\n{outline}"
            
            from ai_platform.core.config import get_settings as _get_settings
            s = _get_settings()
            import httpx as httpx_mod
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=60.0
            )
            
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
                    article = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en generate_article: {e}")
                    article = {"title": topic, "content": response_text, "meta_description": "", "word_count": 0, "keywords": [], "suggested_tags": []}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info(f"Artículo generado: {article.get('title', topic)}")
            
            return {
                "title": article.get("title", topic),
                "meta_description": article.get("meta_description", ""),
                "content": article.get("content", ""),
                "word_count": article.get("word_count", word_count),
                "keywords": article.get("keywords", keywords),
                "suggested_tags": article.get("suggested_tags", [])
            }
        
        except Exception as e:
            logger.error(f"Error generando artículo: {e}")
            return {
                "title": topic,
                "content": f"Error generando artículo: {e}",
                "meta_description": "",
                "word_count": 0,
                "keywords": keywords,
                "error": str(e)
            }
    
    def generate_copy(self, payload: dict) -> dict:
        """
        Generar copys para redes sociales, landing pages o anuncios.
        
        Parámetros:
            payload: {
                "product": "Zapatillas deportivas",
                "platform": "instagram",
                "tone": "divertido",
                "language": "es",
                "features": ["ligeras", "cómodas", "resistentes"]
            }
        
        Retorna:
            {
                "headline": "...",
                "body": "...",
                "cta": "...",
                "hashtags": [...]
            }
        """
        product = scanner.sanitize(payload.get("product", ""))
        platform = scanner.sanitize(payload.get("platform", "instagram"))
        tone = scanner.sanitize(payload.get("tone", "profesional"))
        language = scanner.sanitize(payload.get("language", "es"))
        features = payload.get("features", [])
        tenant_id = payload.get("tenant_id")
        
        if not product:
            raise ValueError("Se requiere 'product' para generar copy")
        
        logger.info(f"Generando copy para: {product} en {platform}")
        
        platform_constraints = {
            "instagram": {"max_length": 2200, "hashtag_count": "8-15", "style": "visual y emotivo"},
            "facebook": {"max_length": 63200, "hashtag_count": "2-5", "style": "conversacional"},
            "linkedin": {"max_length": 3000, "hashtag_count": "3-5", "style": "profesional"},
            "twitter": {"max_length": 280, "hashtag_count": "1-2", "style": "conciso"},
            "google_ads": {"max_length": 90, "hashtag_count": "0", "style": "directo y orientado a conversión"},
        }
        
        constraints = platform_constraints.get(platform, platform_constraints["instagram"])
        
        try:
            from ai_platform.core.config import get_settings as _get_settings
            s = _get_settings()
            import httpx as httpx_mod
            
            system_prompt = (
                f"Eres un copywriter profesional especializado en {platform}.\n"
                f"Tono: {tone}\n"
                f"Estilo: {constraints['style']}\n"
                f"Plataforma: {platform}\n"
                f"Hashtags recomendados: {constraints['hashtag_count']}\n\n"
                f"Responde SIEMPRE en formato JSON:\n"
                f'{{"headline": "...", "body": "...", "cta": "...", "hashtags": [], "character_count": 0}}'
            )
            
            user_prompt = f"Producto/servicio: {product}"
            if features:
                user_prompt += f"\nCaracterísticas destacadas: {', '.join(features)}"
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 1024,
                    "temperature": 0.8,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    copy = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en generate_copy: {e}")
                    copy = {"headline": product, "body": response_text, "cta": "", "hashtags": [], "character_count": 0}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info(f"Copy generado para {product}")
            
            return {
                "headline": copy.get("headline", ""),
                "body": copy.get("body", ""),
                "cta": copy.get("cta", ""),
                "hashtags": copy.get("hashtags", []),
                "character_count": copy.get("character_count", 0),
                "platform": platform
            }
        
        except Exception as e:
            logger.error(f"Error generando copy: {e}")
            return {
                "headline": f"{product}",
                "body": f"Error generando copy: {e}",
                "cta": "",
                "hashtags": [],
                "character_count": 0,
                "error": str(e)
            }
    
    def rewrite_content(self, payload: dict) -> dict:
        """
        Reescribir contenido existente con diferente tono o estilo.
        
        Parámetros:
            payload: {
                "content": "Texto original a reescribir",
                "tone": "divertido",
                "language": "es",
                "goal": "hacerlo más persuasivo"
            }
        
        Retorna:
            {
                "original": "...",
                "rewritten": "...",
                "tone": "divertido",
                "improvements": [...]
            }
        """
        content = scanner.sanitize(payload.get("content", ""))
        tone = scanner.sanitize(payload.get("tone", "profesional"))
        language = scanner.sanitize(payload.get("language", "es"))
        goal = scanner.sanitize(payload.get("goal", "mejorar el texto"))
        tenant_id = payload.get("tenant_id")
        
        if not content:
            raise ValueError("Se requiere 'content' para reescribir")
        
        logger.info(f"Reescribiendo contenido con tono: {tone}")
        
        try:
            from ai_platform.core.config import get_settings as _get_settings
            s = _get_settings()
            import httpx as httpx_mod
            
            system_prompt = (
                f"Eres un editor profesional de texto.\n"
                f"Tono objetivo: {tone}\n"
                f"Idioma: {language}\n"
                f"Objetivo: {goal}\n\n"
                f"Responde SIEMPRE en formato JSON:\n"
                f'{{"rewritten": "...", "original_length": 0, "new_length": 0, "improvements": []}}'
            )
            
            client = httpx_mod.Client(
                base_url=s.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {s.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30.0
            )
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content},
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
                    logger.error(f"JSON inválido de LLM en rewrite_content: {e}")
                    result = {"rewritten": response_text, "original_length": len(content), "new_length": len(response_text), "improvements": []}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info("Contenido reescrito exitosamente")
            
            return {
                "original": content,
                "rewritten": result.get("rewritten", ""),
                "tone": tone,
                "original_length": result.get("original_length", len(content)),
                "new_length": result.get("new_length", 0),
                "improvements": result.get("improvements", [])
            }
        
        except Exception as e:
            logger.error(f"Error reescribiendo contenido: {e}")
            return {
                "original": content,
                "rewritten": content,
                "tone": tone,
                "original_length": len(content),
                "new_length": len(content),
                "improvements": [],
                "error": str(e)
            }
