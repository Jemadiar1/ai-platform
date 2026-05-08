"""
Handler para el módulo ai-social.

Gestión de redes sociales: generar posts, programar publicaciones,
y analizar rendimiento de contenido.

Acciones disponibles:
- generate_post: Crear post para red social específica
- schedule_post: Generar post con metadata de programación
- analyze_performance: Analizar métricas simuladas de rendimiento
"""

from typing import Any
import json
import logging
from datetime import datetime, timezone

from ai_platform.core.config import get_settings
from ai_platform.core.security import scanner

logger = logging.getLogger(__name__)


class Handler:
    """Handler para el módulo ai-social."""
    
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar la acción de redes sociales solicitada.
        
        Parámetros:
            payload: Datos de la tarea con "action" y parámetros
        
        Retorna:
            dict con el resultado de la ejecución
        """
        action = payload.get("action", "default")
        
        actions = {
            "generate_post": self.generate_post,
            "schedule_post": self.schedule_post,
            "analyze_performance": self.analyze_performance,
        }
        
        if action not in actions:
            logger.error(f"Acción no soportada en ai-social: {action}")
            return {
                "action": action,
                "status": "error",
                "error": f"Acción no soportada en ai-social: {action}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        logger.info(f"Ejecutando {action} en ai-social")
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
            logger.error(f"Error ejecutando {action} en ai-social: {e}")
            return {
                "action": action,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    def generate_post(self, payload: dict) -> dict:
        """
        Generar un post para red social específica.
        
        Parámetros:
            payload: {
                "platform": "instagram",
                "topic": "Lanzamiento de producto",
                "tone": "divertido",
                "language": "es",
                "brand_voice": "cercano y energético"
            }
        
        Retorna:
            {"content": "...", "hashtags": [...], "media_suggestions": [...]}
        """
        platform = scanner.sanitize(payload.get("platform", "instagram"))
        topic = scanner.sanitize(payload.get("topic", ""))
        tone = scanner.sanitize(payload.get("tone", "profesional"))
        language = scanner.sanitize(payload.get("language", "es"))
        brand_voice = scanner.sanitize(payload.get("brand_voice", ""))
        include_emoji = payload.get("include_emoji", True)
        product_info = scanner.sanitize(payload.get("product_info", "") or "")
        
        if not topic:
            raise ValueError("Se requiere 'topic' para generar post")
        
        logger.info(f"Generando post para {platform} sobre: {topic}")
        
        platform_templates = {
            "instagram": {
                "type": "visual caption",
                "max_length": 2200,
                "hashtag_count": "8-15",
                "style": "visual, emotivo, con emojis"
            },
            "facebook": {
                "type": "update",
                "max_length": 63200,
                "hashtag_count": "2-5",
                "style": "conversacional, familiar"
            },
            "linkedin": {
                "type": "professional post",
                "max_length": 3000,
                "hashtag_count": "3-5",
                "style": "profesional, orientado a industria"
            },
            "twitter": {
                "type": "tweet",
                "max_length": 280,
                "hashtag_count": "0-2",
                "style": "conciso, impactante"
            },
        }
        
        template = platform_templates.get(platform, platform_templates["instagram"])
        
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
                f"Eres un community manager experto en {platform}.\n"
                f"Tipo de contenido: {template['type']}\n"
                f"Estilo: {template['style']}\n"
                f"Tono: {tone}\n"
                f"Idioma: {language}\n"
                f"Hashtags: {template['hashtag_count']}\n"
            )
            if brand_voice:
                system_prompt += f"\nVoz de marca: {brand_voice}\n"
            if not include_emoji:
                system_prompt += "\nNo usar emojis.\n"
            
            system_prompt += (
                "\nResponde SIEMPRE en formato JSON:\n"
                '{"content": "...", "hashtags": [], "media_suggestions": [], "best_time_post": "10:00", "estimated_engagement": "medium"}'
            )
            
            user_prompt = f"Tema: {topic}"
            if product_info:
                user_prompt += f"\nProducto/empresa: {product_info}"
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 2048,
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
                    logger.error(f"JSON inválido de LLM en generate_post: {e}")
                    result = {"content": f"Post sobre {topic}", "hashtags": [], "media_suggestions": [], "best_time_post": "", "estimated_engagement": "medium"}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info(f"Post generado para {platform}")
            
            return {
                "content": result.get("content", ""),
                "hashtags": result.get("hashtags", []),
                "media_suggestions": result.get("media_suggestions", []),
                "best_time_to_post": result.get("best_time_post", ""),
                "estimated_engagement": result.get("estimated_engagement", "medium"),
                "platform": platform,
                "format": template["type"]
            }
        
        except Exception as e:
            logger.error(f"Error generando post: {e}")
            return {
                "content": f"Post sobre {topic}",
                "hashtags": [],
                "media_suggestions": [],
                "platform": platform,
                "error": str(e)
            }
    
    def schedule_post(self, payload: dict) -> dict:
        """
        Generar post programado con metadata de publicación.
        
        Parámetros:
            payload: {
                "platform": "instagram",
                "topic": "Promoción de verano",
                "scheduled_time": "2026-06-01T10:00:00",
                "tone": "veraniego",
                "language": "es"
            }
        
        Retorna:
            {"post_id": "...", "post_data": {...}, "scheduled_at": "...", "status": "scheduled"}
        """
        platform = scanner.sanitize(payload.get("platform", "instagram"))
        topic = scanner.sanitize(payload.get("topic", ""))
        scheduled_time = payload.get("scheduled_time")
        tone = scanner.sanitize(payload.get("tone", "profesional"))
        language = scanner.sanitize(payload.get("language", "es"))
        brand_voice = scanner.sanitize(payload.get("brand_voice", "") or "")
        recurrence = payload.get("recurrence")  # "daily", "weekly", etc.
        
        if not topic:
            raise ValueError("Se requiere 'topic' para programar post")
        
        logger.info(f"Programando post para {platform} sobre: {topic}")
        
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
                f"Eres un community manager experto en {platform}.\n"
                f"Tono: {tone}\n"
                f"Idioma: {language}\n\n"
                f"Generar un post completo con metadata de programación.\n"
                f"Responde SIEMPRE en formato JSON:\n"
                '{"post_data": {{ "content": "...", "hashtags": [], "media_suggestions": [] }}, '
                '"scheduled_at": "...", "recurrence": null, "social_asset_id": null}'
            )
            
            user_prompt = f"Tema: {topic}\nHora programada: {scheduled_time}"
            if recurrence:
                user_prompt += f"\nRecurrencia: {recurrence}"
            if brand_voice:
                user_prompt += f"\nVoz de marca: {brand_voice}"
            
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
                    logger.error(f"JSON inválido de LLM en schedule_post: {e}")
                    result = {"post_data": {}, "scheduled_at": scheduled_time, "recurrence": None, "social_asset_id": None}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            import uuid
            post_id = str(uuid.uuid4())
            
            logger.info(f"Post programado: {post_id}")
            
            return {
                "post_id": post_id,
                "post_data": result.get("post_data", {}),
                "scheduled_at": result.get("scheduled_at", scheduled_time),
                "recurrence": result.get("recurrence", recurrence),
                "status": "scheduled",
                "platform": platform
            }
        
        except Exception as e:
            logger.error(f"Error programando post: {e}")
            return {
                "post_id": None,
                "post_data": {},
                "scheduled_at": scheduled_time,
                "status": "error",
                "platform": platform,
                "error": str(e)
            }
    
    def analyze_performance(self, payload: dict) -> dict:
        """
        Analizar rendimiento simulado de posts.
        
        Parámetros:
            payload: {
                "platform": "instagram",
                "posts": [{"content": "...", "impressions": 1000, "likes": 50, ...}],
                "date_range": "last_30_days"
            }
        
        Retorna:
            {"summary": {...}, "insights": [...], "recommendations": [...]}
        """
        platform = scanner.sanitize(payload.get("platform", "instagram"))
        posts = payload.get("posts", [])
        date_range = payload.get("date_range", "last_30_days")
        
        logger.info(f"Analizando rendimiento en {platform}: {len(posts)} posts")
        
        # Calcular métricas básicas de las post's proporcionadas
        total_impressions = sum(p.get("impressions", 0) for p in posts)
        total_likes = sum(p.get("likes", 0) for p in posts)
        total_comments = sum(p.get("comments", 0) for p in posts)
        total_shares = sum(p.get("shares", 0) for p in posts)
        
        avg_engagement_rate = 0
        if total_impressions > 0:
            avg_engagement_rate = ((total_likes + total_comments + total_shares) / total_impressions) * 100
        
        top_performing = max(posts, key=lambda p: p.get("likes", 0) + p.get("comments", 0)) if posts else {}
        worst_performing = min(posts, key=lambda p: p.get("likes", 0) + p.get("comments", 0)) if posts else {}
        
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
                "Eres un analista de redes sociales.\n"
                "Analiza los datos de rendimiento y proporciona insights accionables.\n"
                "Responde SIEMPRE en formato JSON:\n"
                '{"insights": [], "recommendations": [], "engagement_analysis": {}}'
            )
            
            metrics_summary = (
                f"Plataforma: {platform}\n"
                f"Período: {date_range}\n"
                f"Posts analizados: {len(posts)}\n"
                f"Impresiones totales: {total_impressions}\n"
                f"Likes: {total_likes}, Comentarios: {total_comments}, Compartidos: {total_shares}\n"
                f"Engagement rate promedio: {avg_engagement_rate:.2f}%\n"
                f"Post mejor funcionando: {top_performing.get('content', 'N/A')[:100]}"
            )
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": metrics_summary},
                    ],
                    "max_tokens": 2048,
                    "temperature": 0.5,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    analysis = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en analyze_performance: {e}")
                    analysis = {"insights": [], "recommendations": [], "engagement_analysis": {}}
            else:
                analysis = {"insights": [], "recommendations": [], "engagement_analysis": {}}
        
        except Exception as e:
            logger.error(f"Error analizando rendimiento: {e}")
            analysis = {"insights": [], "recommendations": [], "engagement_analysis": {}}
        
        logger.info("Análisis de rendimiento completado")
        
        return {
            "summary": {
                "total_posts": len(posts),
                "total_impressions": total_impressions,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "total_shares": total_shares,
                "avg_engagement_rate": round(avg_engagement_rate, 2)
            },
            "insights": analysis.get("insights", [
                f"Engagement rate promedio del {avg_engagement_rate:.2f}% en {platform}",
                f"Post mejor funcionando tuvo {top_performing.get('likes', 0)} likes",
            ] if posts else ["No hay datos suficientes para analizar"],
            ),
            "recommendations": analysis.get("recommendations", [
                "Publicar en horarios pico de actividad",
                "Usar más contenido visual",
                "Incluir calls-to-action en los posts",
            ]),
            "engagement_analysis": analysis.get("engagement_analysis", {
                "engagement_rate_percent": round(avg_engagement_rate, 2),
                "like_rate": round((total_likes / total_impressions * 100) if total_impressions > 0 else 0, 2),
                "comment_rate": round((total_comments / total_impressions * 100) if total_impressions > 0 else 0, 2),
                "share_rate": round((total_shares / total_impressions * 100) if total_impressions > 0 else 0, 2),
            }),
            "top_performing_content": top_performing.get("content", "") if top_performing else "",
            "worst_performing_content": worst_performing.get("content", "") if worst_performing else "",
            "platform": platform
        }
