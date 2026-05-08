"""
Módulo NeuralCrew Connect - Implementación completa.

Connect maneja todos los flujos de comunicación:
- Voz IA (llamadas telefónicas con IA)
- WhatsApp (mensajes automáticos)
- Chat en vivo (integración con sitios web)
- Agenda (reservas y citas)
- CRM básico (gestión de contactos)

¿Por qué este módulo primero?
- Es el que genera valor más rápido
- Un asistente de voz/WhatsApp puede atender clientes 24/7
- Es demostrable en una demo real
- Genera ingresos desde el día 1

Arquitectura:
    handler.py → Punto de entrada (recibe la tarea y la ejecuta)
    whatsapp.py → WhatsApp Business API
    voice.py   → Vapi.ai / Twilio para voz IA
    chat.py    → Chat en vivo (integración web)
    agenda.py  → Google Calendar / Calendly
    crm.py     → CRM básico (contactos, notas, seguimiento)
"""

from typing import Any, Optional
import json
import logging
from datetime import datetime, timezone

import httpx

from ai_platform.core.config import get_settings
from ai_platform.database import session_factory
from ai_platform.models.db import Tenant, Contact
from ai_platform.orchestrator.ragnar import get_ragnar

logger = logging.getLogger(__name__)
settings = get_settings()


class Handler:
    """
    Handler principal del módulo Connect.
    
    Este handler es llamado por el Celery worker cuando llega
    una tarea del módulo ai-connect.
    
    Ejemplo de tarea:
    {
        "module": "ai-connect",
        "payload": {
            "action": "send_whatsapp_message",
            "to": "+521234567890",
            "message": "Hola! Tu cita es mañana a las 10am"
        }
    }
    """
    
    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecutar la acción solicitada.
        
        Parámetros:
            payload: Datos de la tarea con "action" y parámetros
        
        Retorna:
            dict con el resultado de la ejecución
        """
        action = payload.get("action")
        if not action:
            logger.error("No se especificó una acción en Connect")
            return {
                "action": None,
                "status": "error",
                "error": "No se especificó una acción",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        # Dispatcher: elegir la función según la acción
        actions = {
            "send_whatsapp_message": self._send_whatsapp,
            "make_voice_call": self._make_voice_call,
            "handle_chat_message": self._handle_chat,
            "schedule_appointment": self._schedule_appointment,
            "update_contact": self._update_contact,
            "get_contacts": self._get_contacts,
        }
        
        if action not in actions:
            logger.error(f"Acción no soportada en Connect: {action}")
            return {
                "action": action,
                "status": "error",
                "error": f"Acción no soportada: {action}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        logger.info(f"Ejecutando acción {action} del módulo Connect")
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
            logger.info(f"Acción {action} completada")
            return {
                "action": action,
                "status": "success",
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(f"Error ejecutando acción {action} en Connect: {e}")
            return {
                "action": action,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    # ========================================================================
    # WhatsApp
    # ========================================================================
    
    def _send_whatsapp(self, payload: dict) -> dict:
        """
        Enviar mensaje por WhatsApp usando WhatsApp Business API (Meta Cloud API).
        
        Flujo:
        1. Recibir payload con "to" y "message"
        2. Validar número de teléfono (formato E.164)
        3. Enviar mensaje a través de la API de WhatsApp
        4. Retornar ID del mensaje
        
        Parámetros:
            payload: {"to": "+521234567890", "message": "Hola", ...}
        
        Retorna:
            {"message_id": "wamid.xxx", "status": "sent"}
        """
        to = payload.get("to")
        message = payload.get("message")
        template_name = payload.get("template_name")
        template_language = payload.get("template_language", "es")
        
        if not to or (not message and not template_name):
            raise ValueError("Se requieren 'to' y ('message' o 'template_name')")
        
        # Validar formato de teléfono (E.164)
        if not to.startswith("+"):
            raise ValueError("El número debe estar en formato E.164 (ej: +521234567890)")
        
        phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        access_token = settings.WHATSAPP_ACCESS_TOKEN
        
        if not phone_number_id or not access_token:
            logger.warning("WhatsApp credentials no configuradas, usando modo stub")
            return {
                "to": to,
                "status": "stub_no_credentials",
                "message_id": f"stub_{datetime.utcnow().timestamp()}",
                "note": "WHATSAPP_PHONE_NUMBER_ID o WHATSAPP_ACCESS_TOKEN no están configurados"
            }
        
        logger.info(f"Enviando WhatsApp a {to}")
        
        try:
            api_version = "v18.0"
            url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            # Determinar tipo de mensaje y construir el payload
            if template_name:
                # Mensaje de template
                whatsapp_payload = {
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {"code": template_language}
                    }
                }
            else:
                # Mensaje de texto
                whatsapp_payload = {
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {
                        "body": message
                    }
                }
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, headers=headers, json=whatsapp_payload)
            
            if response.status_code == 200:
                response_data = response.json()
                messages = response_data.get("messages", [])
                message_id = messages[0]["id"] if messages else None
                
                logger.info(f"WhatsApp enviado exitosamente a {to}, message_id: {message_id}")
                
                return {
                    "to": to,
                    "status": "sent",
                    "message_id": message_id,
                    "type": "template" if template_name else "text"
                }
            else:
                error_detail = response.text
                logger.error(f"Error enviando WhatsApp: {response.status_code} - {error_detail}")
                return {
                    "to": to,
                    "status": "error",
                    "error_code": response.status_code,
                    "error_detail": error_detail
                }
        
        except httpx.TimeoutException:
            logger.error(f"Timeout al enviar WhatsApp a {to}")
            return {
                "to": to,
                "status": "error",
                "error": "Timeout al conectar con WhatsApp API"
            }
        except httpx.HTTPError as e:
            logger.error(f"Error HTTP enviando WhatsApp a {to}: {e}")
            return {
                "to": to,
                "status": "error",
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"Error inesperado enviando WhatsApp a {to}: {e}")
            return {
                "to": to,
                "status": "error",
                "error": str(e)
            }
    
    # ========================================================================
    # Voz IA
    # ========================================================================
    
    def _make_voice_call(self, payload: dict) -> dict:
        """
        Hacer llamada de voz con IA usando Vapi.ai.
        
        Flujo:
        1. Recibir payload con "phone_number" y "agent_id"
        2. Crear llamada a través de Vapi.ai
        3. Retornar ID de la llamada
        
        Parámetros:
            payload: {"phone_number": "+521234567890", "agent_id": "agent_123", ...}
        
        Retorna:
            {"call_id": "call_123", "status": "initiated"}
        """
        phone_number = payload.get("phone_number")
        agent_id = payload.get("agent_id")
        assistant_name = payload.get("assistant_name", "Asistente NeuralCrew")
        prompt = payload.get("prompt", f"Eres {assistant_name}, un asistente de voz inteligente de NeuralCrew.")
        end_number = payload.get("end_number", phone_number)
        
        if not phone_number:
            raise ValueError("Se requiere 'phone_number'")
        
        if not phone_number.startswith("+"):
            raise ValueError("El número debe estar en formato E.164")
        
        api_key = settings.VAPI_API_KEY
        
        if not api_key:
            logger.warning("VAPI_API_KEY no configurada, usando modo stub")
            return {
                "phone_number": phone_number,
                "agent_id": agent_id,
                "status": "stub_no_credentials",
                "call_id": f"stub_{datetime.utcnow().timestamp()}",
                "note": "VAPI_API_KEY no está configurada"
            }
        
        logger.info(f"Iniciando llamada de voz a {phone_number} con Vapi.ai")
        
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            call_payload = {
                "phoneNumberId": payload.get("phone_number_id"),
                "number": phone_number,
                "assistant": {
                    "name": assistant_name,
                    "firstMessage": "Hola, soy un asistente de NeuralCrew. ¿En qué puedo ayudarte?",
                    "model": {
                        "provider": "openrouter",
                        "stream": True,
                        "data": {
                            "model": "anthropic/claude-3.5-sonnet",
                            "messages": [
                                {"role": "system", "content": prompt}
                            ]
                        }
                    },
                    "endCallMessage": "Gracias por tu llamada. ¿Algo más en lo que pueda ayudarte?"
                }
            }
            
            # Eliminar campos None
            call_payload = {k: v for k, v in call_payload.items() if v is not None}
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.vapi.ai/call",
                    headers=headers,
                    json=call_payload
                )
            
            if response.status_code == 200:
                response_data = response.json()
                call_id = response_data.get("id")
                
                logger.info(f"Llamada de voz iniciada exitosamente, call_id: {call_id}")
                
                return {
                    "phone_number": phone_number,
                    "agent_id": agent_id,
                    "status": "initiated",
                    "call_id": call_id,
                    "assistant_name": assistant_name
                }
            else:
                error_detail = response.text
                logger.error(f"Error en Vapi.ai: {response.status_code} - {error_detail}")
                return {
                    "phone_number": phone_number,
                    "status": "error",
                    "error_code": response.status_code,
                    "error_detail": error_detail
                }
        
        except httpx.TimeoutException:
            logger.error(f"Timeout al crear llamada Vapi.ai para {phone_number}")
            return {
                "phone_number": phone_number,
                "status": "error",
                "error": "Timeout al conectar con Vapi.ai"
            }
        except httpx.HTTPError as e:
            logger.error(f"Error HTTP en Vapi.ai: {e}")
            return {
                "phone_number": phone_number,
                "status": "error",
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"Error inesperado en Vapi.ai: {e}")
            return {
                "phone_number": phone_number,
                "status": "error",
                "error": str(e)
            }
    
    # ========================================================================
    # Chat en vivo
    # ========================================================================
    
    def _handle_chat(self, payload: dict) -> dict:
        """
        Manejar mensaje de chat en vivo usando el orquestador Ragnar.
        
        Flujo:
        1. Recibir mensaje del chat
        2. Enviar al orquestador Ragnar para generar respuesta IA
        3. Retornar respuesta al chat
        
        Parámetros:
            payload: {"message": "Hola, quiero información", "context": {...}}
        
        Retorna:
            {"message": "...", "response": "...", "status": "handled"}
        """
        message = payload.get("message")
        context = payload.get("context", {})
        session_id = context.get("session_id")
        tenant_id = context.get("tenant_id", context.get("tenant"))
        
        if not message:
            raise ValueError("Se requiere 'message'")
        
        logger.info(f"Manejando chat: {message[:50]}...")
        
        try:
            # Usar Ragnar orquestador para generar respuesta IA
            ragnar = get_ragnar()
            
            # Construir prompt completo con contexto
            full_prompt = message
            if tenant_id:
                full_prompt = f"[Tenant: {tenant_id}] {message}"
            
            decision = ragnar.decide(
                prompt=message,
                tenant_id=str(tenant_id) if tenant_id else "unknown",
                session_id=session_id
            )
            
            # Extraer la respuesta del asistente
            assistant_response = decision.get("params", {}).get("response", "")
            
            # Si Ragnar no generó respuesta directa, usar el reasoning como fallback
            if not assistant_response:
                assistant_response = decision.get("reasoning", "No se pudo generar una respuesta.")
            
            logger.info(f"Respuesta IA generada para chat")
            
            return {
                "message": message,
                "response": assistant_response,
                "status": "handled",
                "session_id": decision.get("session_id"),
                "module": decision.get("module"),
                "confidence": decision.get("confidence")
            }
        
        except Exception as e:
            logger.error(f"Error generando respuesta IA para chat: {e}")
            return {
                "message": message,
                "response": "Lo siento, hubo un error generando la respuesta. Por favor intenta de nuevo.",
                "status": "error",
                "error": str(e)
            }
    
    # ========================================================================
    # Agenda
    # ========================================================================
    
    def _schedule_appointment(self, payload: dict) -> dict:
        """
        Programar cita.
        
        Integra con Google Calendar o Calendly para programar citas.
        
        Flujo:
        1. Recibir payload con "date", "time", "title", "participants"
        2. Verificar disponibilidad del calendario
        3. Crear evento en el calendario
        4. Enviar confirmación por WhatsApp/email
        5. Retornar ID del evento
        
        Parámetros:
            payload: {"date": "2026-05-15", "time": "10:00", "title": "Consulta", ...}
        
        Retorna:
            {"event_id": "evt_123", "status": "scheduled", "calendar_link": "..."}
        """
        date = payload.get("date")
        time = payload.get("time")
        title = payload.get("title", "Cita")
        participants = payload.get("participants", [])
        description = payload.get("description", "")
        
        if not date or not time:
            raise ValueError("Se requieren 'date' y 'time'")
        
        logger.info(f"Programando cita: {title} el {date} a las {time}")
        
        # TODO: Integrar con Google Calendar o Calendly
        return {
            "date": date,
            "time": time,
            "title": title,
            "status": "scheduled",
            "event_id": f"stub_{datetime.utcnow().timestamp()}",
            "note": "Stub - integrar con Google Calendar"
        }
    
    # ========================================================================
    # CRM
    # ========================================================================
    
    def _update_contact(self, payload: dict) -> dict:
        """
        Actualizar o crear contacto en CRM usando SQLAlchemy.
        
        Si se proporciona contact_id, actualiza el contacto existente.
        Si no, crea un nuevo contacto.
        
        Parámetros:
            payload: {
                "contact_id": "optional-uuid",
                "name": "Juan Pérez",
                "email": "juan@email.com",
                "phone": "+521234567890",
                "notes": "Cliente potencial",
                "extra_data": {"source": "website"},
                "tenant_id": "uuid"
            }
        
        Retorna:
            {"contact_id": "uuid", "status": "created"/"updated"}
        """
        contact_id = payload.get("contact_id")
        tenant_id = payload.get("tenant_id")
        name = payload.get("name")
        email = payload.get("email")
        phone = payload.get("phone")
        notes = payload.get("notes", "")
        extra_data = payload.get("extra_data", {})
        
        if not name and not email and not phone:
            raise ValueError("Se requiere al menos 'name', 'email' o 'phone'")
        
        session = session_factory()
        try:
            if contact_id:
                # Actualizar contacto existente
                contact = session.query(Contact).filter(
                    (Contact.id == contact_id) | (Contact.email == email)
                ).first()
                
                if not contact:
                    raise ValueError(f"Contacto no encontrado: {contact_id}")
                
                if name:
                    contact.name = name
                if email:
                    contact.email = email
                if phone is not None:
                    contact.phone = phone
                if notes:
                    contact.notes = notes
                if extra_data:
                    contact.extra_data = extra_data
                
                logger.info(f"Contacto actualizado: {contact.name or contact.email}")
                status_result = "updated"
            else:
                # Crear nuevo contacto
                # Buscar si ya existe por email para evitar duplicados
                existing = session.query(Contact).filter_by(email=email).first() if email else None
                
                if existing:
                    # Actualizar existente por email
                    if name:
                        existing.name = name
                    if phone is not None:
                        existing.phone = phone
                    if notes:
                        existing.notes = notes
                    if extra_data:
                        existing.extra_data = extra_data
                    contact = existing
                    logger.info(f"Contacto actualizado por email: {email}")
                    status_result = "updated"
                else:
                    # Crear nuevo
                    contact = Contact(
                        tenant_id=tenant_id,
                        name=name or "",
                        email=email or "",
                        phone=phone or "",
                        notes=notes or "",
                        extra_data=extra_data or {}
                    )
                    session.add(contact)
                    logger.info(f"Contacto creado: {name or email}")
                    status_result = "created"
            
            session.commit()
            
            return {
                "contact_id": str(contact.id),
                "status": status_result,
                "name": contact.name,
                "email": contact.email,
                "phone": contact.phone,
                "created_at": contact.created_at.isoformat() if contact.created_at else None,
                "updated_at": contact.updated_at.isoformat() if contact.updated_at else None
            }
        
        except Exception as e:
            session.rollback()
            logger.error(f"Error actualizando contacto: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
        finally:
            session.close()
    
    def _get_contacts(self, payload: dict) -> dict:
        """
        Listar contactos con búsqueda, paginación y filtro por tenant.
        
        Parámetros:
            payload: {
                "tenant_id": "uuid",
                "search": "juan",
                "limit": 50,
                "offset": 0
            }
        
        Retorna:
            {
                "contacts": [...],
                "total": 10,
                "limit": 50,
                "offset": 0
            }
        """
        tenant_id = payload.get("tenant_id")
        search = payload.get("search", "")
        limit = payload.get("limit", 50)
        offset = payload.get("offset", 0)
        
        logger.info(f"Listando contactos (tenant: {tenant_id}, search: {search})")
        
        session = session_factory()
        try:
            query = session.query(Contact)
            
            # Filtrar por tenant si se proporciona
            if tenant_id:
                query = query.filter(Contact.tenant_id == tenant_id)
            
            # Búsqueda por nombre, email o teléfono
            if search:
                search_pattern = f"%{search}%"
                query = query.filter(
                    (Contact.name.ilike(search_pattern)) |
                    (Contact.email.ilike(search_pattern)) |
                    (Contact.phone.ilike(search_pattern))
                )
            
            # Obtener total antes de paginar
            total = query.count()
            
            # Aplicar paginación
            contacts = query.order_by(Contact.updated_at.desc()).limit(limit).offset(offset).all()
            
            # Convertir a diccionarios
            contacts_list = []
            for contact in contacts:
                contacts_list.append({
                    "id": str(contact.id),
                    "name": contact.name,
                    "email": contact.email,
                    "phone": contact.phone,
                    "notes": contact.notes,
                    "extra_data": contact.extra_data,
                    "created_at": contact.created_at.isoformat() if contact.created_at else None,
                    "updated_at": contact.updated_at.isoformat() if contact.updated_at else None
                })
            
            return {
                "contacts": contacts_list,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total
            }
        
        except Exception as e:
            logger.error(f"Error listando contactos: {e}")
            return {
                "contacts": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "error": str(e)
            }
        finally:
            session.close()
