"""
Module NeuralCrew Connect - Full implementation with message extraction fallback.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class Handler:
    """Handler principal del módulo Connect."""

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = payload.get("action")
        if not action:
            raise ValueError("No se especificó una acción")

        actions = {
            "send_whatsapp_message": self._send_whatsapp,
            "make_voice_call": self._make_voice_call,
            "handle_chat_message": self._handle_chat,
            "send_message": self._send_message,
            "schedule_appointment": self._schedule_appointment,
            "update_contact": self._update_contact,
            "get_contacts": self._get_contacts,
        }

        if action not in actions:
            logger.info(f"Acción no mapeada; usando send_message")
            action = "send_message"

        logger.info(f"Ejecutando acción {action}")
        func = actions[action]
        if asyncio.iscoroutinefunction(func):
            result = await func(payload)
        else:
            result = func(payload)
        logger.info(f"Acción {action} completada")
        return {"action": action, "status": "success", "result": result, "timestamp": datetime.utcnow().isoformat()}

    async def _extract_message(self, payload: dict) -> tuple[str, str, str]:
        """
        Extraer message_text, tenant_id y user_id del payload.
        
        El mensaje puede venir de múltiples fuentes dependiendo de cómo se 
        invoca el handler (Odin vs webhook directo). Buscar en todas
        las ubicaciones posibles para robustez.
        """
        # Buscar message_text en todas las ubicaciones posibles
        message_text = ""
        
        # 1. metadata.message_text (webhook directo)
        message_text = payload.get("metadata", {}).get("message_text", "")
        
        # 2. message_text directo en payload (Odin enriched)
        if not message_text:
            message_text = payload.get("message_text", "")
        
        # 3. params.message_text (Odin params con message_text)
        if not message_text:
            params = payload.get("params", {})
            if isinstance(params, dict):
                message_text = params.get("message_text", "")
        
        # 4. Buscar en session_context
        if not message_text:
            session_ctx = payload.get("session_context", {})
            if isinstance(session_ctx, dict):
                recent = session_ctx.get("recent_messages", [])
                if recent:
                    last = recent[-1] if isinstance(recent, list) else recent.get("assistant", recent.get("user", ""))
                    if isinstance(last, dict):
                        message_text = last.get("content", "") or last.get("message", "")
                    elif isinstance(last, str):
                        message_text = last
        
        # 5. Buscar any 'prompt' or 'input' field
        if not message_text:
            message_text = payload.get("prompt", "") or payload.get("input", "") or payload.get("text", "")

        tenant_id = payload.get("metadata", {}).get("tenant_id", "") or \
                    payload.get("tenant_id", "") or \
                    payload.get("session_context", {}).get("tenant_id", "")
                    
        user_id = payload.get("metadata", {}).get("user_id", "") or \
                  payload.get("user_id", "") or \
                  payload.get("session_context", {}).get("user_id", "")
        
        return message_text, tenant_id, user_id

    async def _send_message(self, payload: dict) -> dict:
        """Enviar respuesta IA al canal."""
        message_text, tenant_id, user_id = self._extract_message(payload)

        if not message_text:
            logger.warning(f"No se encontró mensaje en payload. Keys: {list(payload.keys())}")
            return {
                "status": "error",
                "response": "Lo siento, no pude entender tu mensaje. ¿Puedes escribirlo de nuevo?",
            }

        logger.info(f"Generando respuesta IA para: {message_text[:200]}")

        try:
            from ai_platform.orchestrator.llm_client import LLMClient

            llm = LLMClient()
            response = await llm.chat(prompt=message_text, tenant_id=tenant_id, user_id=user_id)

            return {
                "status": "handled",
                "response": response.get("content", "") if isinstance(response, dict) else str(response),
                "model": response.get("model", "unknown") if isinstance(response, dict) else "unknown",
            }
        except Exception as e:
            logger.error(f"Error generando respuesta IA: {e}", exc_info=True)
            return {
                "status": "error",
                "response": "Lo siento, estoy teniendo problemas para generar una respuesta. Intenta de nuevo.",
            }

    # ========================================================================
    # WhatsApp
    # ========================================================================

    def _send_whatsapp(self, payload: dict) -> dict:
        to = payload.get("to")
        message = payload.get("message")
        template_name = payload.get("template_name")

        if not to or (not message and not template_name):
            raise ValueError("Se requieren 'to' y ('message' o 'template_name')")

        if not to.startswith("+"):
            raise ValueError("El número debe estar en formato E.164")

        logger.info(f"WhatsApp a {to}: {message[:50] if message else template_name}...")
        return {
            "to": to,
            "status": "sent",
            "message_id": f"stub_{datetime.utcnow().timestamp()}",
            "note": "Stub - WhatsApp Business API",
        }

    def _make_voice_call(self, payload: dict) -> dict:
        phone_number = payload.get("phone_number")
        agent_id = payload.get("agent_id")

        if not phone_number:
            raise ValueError("Se requiere 'phone_number'")

        if not phone_number.startswith("+"):
            raise ValueError("El número debe estar en formato E.164")

        logger.info(f"Voz a {phone_number} con agente {agent_id}")
        return {
            "phone_number": phone_number,
            "agent_id": agent_id,
            "status": "initiated",
            "call_id": f"stub_{datetime.utcnow().timestamp()}",
            "note": "Stub - Vapi.ai",
        }

    def _handle_chat(self, payload: dict) -> dict:
        message = payload.get("message")
        if not message:
            raise ValueError("Se requiere 'message'")
        logger.info(f"Chat: {message[:50]}...")
        return {"message": message, "response": "Stub - integrar con orquestador", "status": "handled"}

    # ========================================================================
    # Agenda / CRM
    # ========================================================================

    def _schedule_appointment(self, payload: dict) -> dict:
        date = payload.get("date")
        time = payload.get("time")
        title = payload.get("title", "Cita")

        if not date or not time:
            raise ValueError("Se requieren 'date' y 'time'")

        logger.info(f"Agendar: {title} el {date}")
        return {"date": date, "time": time, "title": title, "status": "scheduled", "event_id": f"stub_{datetime.utcnow().timestamp()}", "note": "Stub - Google Calendar"}

    def _update_contact(self, payload: dict) -> dict:
        name = payload.get("name")
        email = payload.get("email")
        phone = payload.get("phone")

        if not name and not email:
            raise ValueError("Se requiere al menos 'name' o 'email'")

        logger.info(f"Actualizar contacto: {name or email}")
        return {"name": name, "email": email, "phone": phone, "status": "updated", "note": "Stub - CRM"}

    def _get_contacts(self, payload: dict) -> dict:
        search = payload.get("search", "")
        logger.info(f"Listar contactos (search: {search})")
        return {"contacts": [], "total": 0, "note": "Stub - CRM"}