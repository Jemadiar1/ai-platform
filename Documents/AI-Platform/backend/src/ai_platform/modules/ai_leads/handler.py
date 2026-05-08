"""
Handler para el módulo ai-leads.

Generación, puntuación y enriquecimiento de leads.

Acciones disponibles:
- generate_leads: Generar lista de leads potenciales
- score_lead: Calificar/un lead basado en criterios
- enrich_lead: Enriquecer datos de un lead existente
"""

from typing import Any
import json
import logging
from datetime import datetime, timezone

from ai_platform.core.config import get_settings
from ai_platform.core.security import scanner

logger = logging.getLogger(__name__)


class Handler:
    """Handler para el módulo ai-leads."""
    
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar la acción de leads solicitada.
        
        Parámetros:
            payload: Datos de la tarea con "action" y parámetros
        
        Retorna:
            dict con el resultado de la ejecución
        """
        action = payload.get("action", "default")
        
        actions = {
            "generate_leads": self.generate_leads,
            "score_lead": self.score_lead,
            "enrich_lead": self.enrich_lead,
        }
        
        if action not in actions:
            logger.error(f"Acción no soportada en ai-leads: {action}")
            return {
                "action": action,
                "status": "error",
                "error": f"Acción no soportada en ai-leads: {action}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        logger.info(f"Ejecutando {action} en ai-leads")
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
            logger.error(f"Error ejecutando {action} en ai-leads: {e}")
            return {
                "action": action,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    def generate_leads(self, payload: dict) -> dict:
        """
        Generar leads potenciales basados en criterios de negocio.
        
        Parámetros:
            payload: {
                "industry": "tecnología",
                "company_size": "50-200 empleados",
                "target_role": "CTO",
                "budget_range": "$10k-$50k",
                "geography": "Latinoamérica",
                "language": "es"
            }
        
        Retorna:
            {"leads": [{"name": "...", "company": "...", "score": 85, ...}], "total": 5}
        """
        industry = scanner.sanitize(payload.get("industry", ""))
        company_size = scanner.sanitize(payload.get("company_size", ""))
        target_role = scanner.sanitize(payload.get("target_role", "decision_maker"))
        budget_range = scanner.sanitize(payload.get("budget_range", ""))
        geography = scanner.sanitize(payload.get("geography", ""))
        language = scanner.sanitize(payload.get("language", "es"))
        product_type = scanner.sanitize(payload.get("product_type", ""))
        
        if not industry:
            raise ValueError("Se requiere 'industry' para generar leads")
        
        logger.info(f"Generando leads en industria: {industry}")
        
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
                f"Eres un experto en generación de leads B2B.\n"
                f"Genera leads relevantes para un negocio en {industry}.\n"
                f"Rol objetivo: {target_role}\n"
                f"Tamaño de empresa: {company_size or 'varios'}\n"
            )
            if geography:
                system_prompt += f"\nGeografía: {geography}\n"
            if budget_range:
                system_prompt += f"Rango de presupuesto: {budget_range}\n"
            
            system_prompt += (
                "\nResponde SIEMPRE en formato JSON:\n"
                '{"leads": [{"name": "Nombre", "company": "Empresa", "role": "Cargo", '
                '"email_suggestion": "email@empresa.com", "phone_suggestion": "+000", '
                '"company_size": "", "industry": "", "score": 0, "confidence": 0.5, '
                '"why_relevant": "...", "next_action": "..."}], '
                '"total": 0, "generation_notes": "..."}'
            )
            
            user_prompt = f"Productos/servicios relevantes: {product_type or 'soluciones empresariales'}"
            if industry:
                user_prompt += f"\nIndustrias objetivo: {industry}"
            if company_size:
                user_prompt += f"\nTamaño de empresa: {company_size}"
            
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
                    logger.error(f"JSON inválido de LLM en generate_leads: {e}")
                    result = {"leads": [], "total": 0, "generation_notes": ""}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            leads = result.get("leads", [])
            for lead in leads:
                lead.setdefault("score", 50)
                lead.setdefault("confidence", 0.5)
                lead.setdefault("why_relevant", "")
                lead.setdefault("next_action", "")
            
            logger.info(f"{len(leads)} leads generados para {industry}")
            
            return {
                "leads": leads,
                "total": len(leads),
                "generation_notes": result.get("generation_notes", ""),
                "industry": industry,
                "target_role": target_role
            }
        
        except Exception as e:
            logger.error(f"Error generando leads: {e}")
            return {
                "leads": [],
                "total": 0,
                "industry": industry,
                "error": str(e)
            }
    
    def score_lead(self, payload: dict) -> dict:
        """
        Calificar un lead basado en criterios de calidad.
        
        Parámetros:
            payload: {
                "lead": {
                    "name": "Juan Pérez",
                    "company": "TechCorp",
                    "role": "CTO",
                    "email": "juan@techcorp.com",
                    "source": "landing_page"
                },
                "criteria": {
                    "company_size_min": 10,
                    "industry_match": true,
                    "budget_confirmed": false
                },
                "language": "es"
            }
        
        Retorna:
            {"lead_id": "...", "score": 75, "grade": "B", "factors": [...]}
        """
        lead = payload.get("lead", {})
        criteria = payload.get("criteria", {})
        language = payload.get("language", "es")
        
        name = scanner.sanitize(lead.get("name", "") if isinstance(lead.get("name"), str) else "")
        company = scanner.sanitize(lead.get("company", "") if isinstance(lead.get("company"), str) else "")
        role = scanner.sanitize(lead.get("role", "") if isinstance(lead.get("role"), str) else "")
        email = scanner.sanitize(lead.get("email", "") if isinstance(lead.get("email"), str) else "")
        source = scanner.sanitize(lead.get("source", "") if isinstance(lead.get("source"), str) else "")
        industry = scanner.sanitize(lead.get("industry", "") if isinstance(lead.get("industry"), str) else "")
        company_size = scanner.sanitize(lead.get("company_size", "") if isinstance(lead.get("company_size"), str) else "")
        
        if not name and not email:
            raise ValueError("Se requiere 'name' o 'email' para calificar lead")
        
        logger.info(f"Calificando lead: {name or email}")
        
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
                "Eres un experto en scoring de leads B2B.\n"
                "Calificar leads basándose en su fit con el perfil ideal de cliente.\n"
                "Criterios actuales:\n"
                "- Fit de industria y mercado\n"
                "- Rol y autoridad de decisión\n"
                "- Budget y disponibilidad\n"
                "- Fuente del lead y engagement\n"
                "- Tamaño y perfil de empresa\n\n"
                "Responde SIEMPRE en formato JSON:\n"
                '{"score": 0, "grade": "A|B|C|D", '
                '"factors": [{"factor": "...", "score": 0, "comment": "..."}], '
                '"recommendation": "...", "next_steps": []}'
            )
            
            lead_summary = (
                f"Lead: {name}\nEmpresa: {company}\nRol: {role}\nEmail: {email}\n"
                f"Fuente: {source}\nIndustria: {industry}\nTamaño: {company_size}"
            )
            if criteria:
                lead_summary += f"\nCriterios: {json.dumps(criteria)}"
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": lead_summary},
                    ],
                    "max_tokens": 2048,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en score_lead: {e}")
                    result = {"score": 50, "grade": "C", "factors": [], "recommendation": "", "next_steps": []}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            logger.info(f"Lead calificado: {name} con score {result.get('score', 0)}")
            
            return {
                "lead_id": lead.get("id"),
                "name": name,
                "company": company,
                "score": result.get("score", 50),
                "grade": result.get("grade", "C"),
                "factors": result.get("factors", []),
                "recommendation": result.get("recommendation", ""),
                "next_steps": result.get("next_steps", [])
            }
        
        except Exception as e:
            logger.error(f"Error calificando lead: {e}")
            return {
                "lead_id": lead.get("id"),
                "name": name,
                "score": 50,
                "grade": "C",
                "factors": [],
                "recommendation": "",
                "next_steps": [],
                "error": str(e)
            }
    
    def enrich_lead(self, payload: dict) -> dict:
        """
        Enriquecer datos de un lead existente con información adicional.
        
        Parámetros:
            payload: {
                "lead": {
                    "name": "Juan Pérez",
                    "company": "TechCorp",
                    "email": "juan@techcorp.com"
                },
                "fields_to_enrich": ["company_size", "industry", "phone", "linkedin"]
            }
        
        Retorna:
            {"lead": {...}, "enriched_fields": ["industry", "company_size"], "confidence": 0.8}
        """
        lead = payload.get("lead", {})
        fields_to_enrich = payload.get("fields_to_enrich", ["company_size", "industry"])
        language = payload.get("language", "es")
        
        name = scanner.sanitize(lead.get("name", "") if isinstance(lead.get("name"), str) else "")
        company = scanner.sanitize(lead.get("company", "") if isinstance(lead.get("company"), str) else "")
        email = scanner.sanitize(lead.get("email", "") if isinstance(lead.get("email"), str) else "")
        
        if not name and not email:
            raise ValueError("Se requiere al menos 'name' o 'email' para enriquecer lead")
        
        logger.info(f"Enriqueciendo datos de lead: {name or email}")
        
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
                f"Eres un sistema de enriquecimiento de datos B2B.\n"
                f"Inferir información adicional sobre un lead a partir de sus datos básicos.\n"
                f"Campos a enriquecer: {', '.join(fields_to_enrich)}\n\n"
                f"Responde SIEMPRE en formato JSON:\n"
                '{"enriched_data": {{}}, "confidence_scores": {{}}, '
                '"source_hints": "..." }'
            )
            
            lead_context = (
                f"Nombre: {name}\n"
                f"Empresa: {company}\n"
                f"Email: {email}\n"
                f"Datos actuales: {json.dumps(lead)}"
            )
            
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "anthropic/claude-3.5-sonnet",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": lead_context},
                    ],
                    "max_tokens": 1024,
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON inválido de LLM en enrich_lead: {e}")
                    result = {"enriched_data": {}, "confidence_scores": {}, "source_hints": ""}
            else:
                raise Exception(f"LLM error: {response.status_code} {response.text}")
            
            enriched_data = result.get("enriched_data", {})
            confidence_scores = result.get("confidence_scores", {})
            
            logger.info(f"Lead enriquecido con {len(enriched_data)} campos nuevos")
            
            return {
                "lead": {**lead},
                "enriched_data": enriched_data,
                "confidence_scores": confidence_scores,
                "enriched_fields": list(enriched_data.keys()),
                "overall_confidence": round(
                    sum(confidence_scores.values()) / len(confidence_scores)
                    if confidence_scores else 0, 2
                ),
                "source_hints": result.get("source_hints", "")
            }
        
        except Exception as e:
            logger.error(f"Error enriqueciendo lead: {e}")
            return {
                "lead": lead,
                "enriched_data": {},
                "confidence_scores": {},
                "enriched_fields": [],
                "overall_confidence": 0,
                "error": str(e)
            }
