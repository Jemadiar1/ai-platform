"""
Handler de webhook para WhatsApp (mensajes entrantes).

Este módulo maneja los webhooks de Meta/Facebook para mensajes
entrantes de WhatsApp Business API. No maneja el envío (eso está
en ai_connect.handler), solo la recepción de mensajes entrantes.

Configuración:
- WHATSAPP_PHONE_NUMBER_ID: ID del número de teléfono de WhatsApp
- WHATSAPP_ACCESS_TOKEN: Token de acceso de la app de Facebook
- WHATSAPP_WEBHOOK_VERIFY_TOKEN: Token de verificación del webhook

"""

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from ai_platform.channels.base import BaseChannel
from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)


class WhatsAppChannel(BaseChannel):
    """
    Handler de canal para WhatsApp (Meta Business API).

    Maneja webhooks entrantes de mensajes de WhatsApp.
    Para el envío reutiliza el handler de ai_connect.
    """

    channel = "whatsapp"

    def __init__(self):
        self.settings = get_settings()
        self.phone_number_id = self.settings.WHATSAPP_PHONE_NUMBER_ID
        self.access_token = self.settings.WHATSAPP_ACCESS_TOKEN
        self.verify_token = self.settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
        self.base_url = "https://graph.facebook.com/v18.0"

    async def validate_webhook(self, payload: Any, headers: dict | None = None) -> dict:
        """
        Validar el webhook de Meta/Facebook.

        Meta envía un GET con challenge para verificar el webhook.
        Para POST (mensajes), se verifica la firma HMAC-SHA256 usando
        el WHATSAPP_APP_SECRET y el header X-Hub-Signature-256.
        Si no hay firma, se valida la estructura del payload.

        Parámetros:
            payload: Dict con el payload del webhook
            headers: Diccionario con los headers HTTP (opcional)

        Retorna:
            Dict con claves:
                - valid: bool, si el webhook es válido
                - reason: str, razón de invalidación si aplica
        """
        if not isinstance(payload, dict):
            logger.warning("Payload de WhatsApp no es un dict")
            return {"valid": False, "reason": "payload_no_es_dict"}

        # Verificar firma HMAC-SHA256 si está disponible
        signature_valid = self._verify_webhook_signature(payload, headers)
        if signature_valid is False:
            logger.warning("Firma HMAC-SHA256 de WhatsApp inválida")
            return {"valid": False, "reason": "firma_hmac_invalida"}

        # Verificar estructura del entry/change
        entries = payload.get("entry", [])
        if not entries:
            logger.warning("Webhook de WhatsApp sin entries")
            return {"valid": False, "reason": "sin_entries"}

        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                if messages:
                    # Validar que el mensaje venga de Meta
                    for msg in messages:
                        from_info = msg.get("from", {})
                        if not from_info:
                            logger.warning("Mensaje de WhatsApp sin from")
                            return {"valid": False, "reason": "mensaje_sin_from"}

        return {"valid": True, "reason": "webhook_valido"}

    def _verify_webhook_signature(self, payload: dict, headers: dict | None = None) -> bool | None:
        """
        Verificar la firma HMAC-SHA256 del webhook de Meta.

        Meta firma los webhooks de WhatsApp Business API con HMAC-SHA256
        usando el WHATSAPP_APP_SECRET. La firma se envía en el header
        X-Hub-Signature-256 o en el campo x-hub-signature-256 del body.

        Parámetros:
            payload: Payload del webhook (como dict)
            headers: Diccionario con los headers HTTP

        Retorna:
            True si la firma es válida, False si no coincide,
            None si no hay firma que verificar (sin secret configurado)
        """
        app_secret = self.settings.WHATSAPP_APP_SECRET
        if not app_secret:
            # Si no hay app_secret configurado, no verificar firma
            # Esto permite desarrollo local sin configuración de firma
            logger.debug("WHATSAPP_APP_SECRET no configurado, saltando verificación de firma")
            return None

        # Obtener la firma del header X-Hub-Signature-256
        signature = None
        if headers:
            # El header puede venir con cualquier mayúsculas/minúsculas en HTTP
            for header_name, header_value in headers.items():
                if header_name.lower() == "x-hub-signature-256":
                    signature = header_value
                    break

        if not signature:
            logger.warning("X-Hub-Signature-256 no encontrado en headers")
            return False

        # Extraer el hash de la firma (formato: "sha256=...")
        if signature.startswith("sha256="):
            signature_hash = signature[7:]
        else:
            logger.warning("Formato de firma X-Hub-Signature-256 inválido")
            return False

        # Convertir el payload dict a JSON para verificar la firma
        payload_json = json.dumps(payload, separators=(",", ":"))

        # Calcular HMAC-SHA256 esperado
        expected_signature = hmac.new(
            app_secret.encode("utf-8"),
            payload_json.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Comparar firmas de forma segura contra timing attacks
        result = hmac.compare_digest(expected_signature, signature_hash)
        if not result:
            logger.error("Firma HMAC-SHA256 no coincide para webhook de WhatsApp")

        return result

    async def extract_message(self, raw_payload: Any) -> dict[str, str]:
        """
        Extraer información del mensaje desde el webhook de Meta.

        Formato de entrada:
        {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "WA_BA_ID",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "+521234567890",
                            "phone_number_id": "PHONE_NUMBER_ID"
                        },
                        "contacts": [{
                            "wa_id": "521234567890",
                            "name": "Juan"
                        }],
                        "messages": [{
                            "from": "521234567890",
                            "id": "wamid.xxx",
                            "timestamp": "1234567890",
                            "text": {
                                "body": "Hola, necesito ayuda"
                            },
                            "type": "text"
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        Parámetros:
            raw_payload: Payload del webhook de Meta

        Retorna:
            {
                "user_id": "521234567890",
                "user_name": "Juan",
                "message_text": "Hola, necesito ayuda",
                "chat_id": "521234567890"
            }
        """
        if not isinstance(raw_payload, dict):
            return {
                "user_id": "",
                "user_name": "",
                "message_text": "",
                "chat_id": "",
            }

        entries = raw_payload.get("entry", [])
        if not entries:
            return {
                "user_id": "",
                "user_name": "",
                "message_text": "",
                "chat_id": "",
            }

        entry = entries[0]
        changes = entry.get("changes", [])
        if not changes:
            return {
                "user_id": "",
                "user_name": "",
                "message_text": "",
                "chat_id": "",
            }

        change = changes[0]
        value = change.get("value", {})
        contacts = value.get("contacts", [])
        messages = value.get("messages", [])

        if not messages:
            return {
                "user_id": "",
                "user_name": "",
                "message_text": "",
                "chat_id": "",
            }

        msg = messages[0]
        from_number = msg.get("from", "")

        # Extraer nombre del contacto
        user_name = ""
        if contacts:
            user_name = contacts[0].get("name", "")

        # Extraer texto del mensaje
        message_text = ""
        if msg.get("type") == "text":
            message_text = msg.get("text", {}).get("body", "")
        elif msg.get("type") == "button":
            message_text = msg.get("button", {}).get("text", "")
        elif msg.get("type") == "interactive":
            message_text = msg.get("interactive", {}).get("nfm_reply", {}).get("response_body", "")

        # WhatsApp usa wa_id como identificador único
        user_id = from_number

        return {
            "user_id": user_id,
            "user_name": user_name or "Usuario WhatsApp",
            "message_text": message_text,
            "chat_id": user_id,
        }

    async def send_message(
        self,
        chat_id: str,
        text: str,
        template_name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Enviar mensaje por WhatsApp usando la Meta API.

        El parámetro chat_id es el número de teléfono en formato E.164.
        Si se proporciona template_name, envía un mensaje template.
        De lo contrario, envía un mensaje de texto simple.

        Parámetros:
            chat_id: Número de teléfono del destinatario (formato E.164, ej: "521234567890")
            text: Contenido del mensaje
            template_name: Nombre de template (opcional)
            **kwargs: Parámetros adicionales (actualmente no usados)

        Retorna:
            Dict con resultado de la API (messages con message_id)
        """
        if not self.access_token:
            logger.error("No se puede enviar mensaje: WHATSAPP_ACCESS_TOKEN no configurado")
            return {"status": "error", "message": "Token no configurado"}

        if not chat_id:
            logger.error("No se puede enviar mensaje: número de teléfono no proporcionado")
            return {"status": "error", "message": "Teléfono no proporcionado"}

        # En WhatsApp, chat_id es el número de teléfono
        phone = chat_id.strip().lstrip("+").replace(" ", "")

        url = f"{self.base_url}/{self.phone_number_id}/messages"

        if template_name:
            payload = {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": "es"},
                },
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "text",
                "text": {
                    "body": text,
                },
            }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()

                messages = data.get("messages", [])
                if messages:
                    logger.info(f"Mensaje WhatsApp enviado a {phone}")
                    return {
                        "status": "sent",
                        "message_id": messages[0].get("id"),
                        "messaging_product": "whatsapp",
                    }
                else:
                    logger.error(f"Error enviando WhatsApp: {data}")
                    return {"status": "error", "message": str(data)}

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error enviando WhatsApp: {e.response.status_code} - {e.response.text}")
            return {"status": "error", "message": f"HTTP {e.response.status_code}"}
        except httpx.RequestError as e:
            logger.error(f"Error de red enviando WhatsApp: {e}")
            return {"status": "error", "message": "Error de red"}
        except Exception as e:
            logger.error(f"Error inesperado enviando WhatsApp: {e}")
            return {"status": "error", "message": str(e)}

    async def verify_webhook_challenge(
        self,
        mode: str,
        token: str,
        challenge: str,
    ) -> dict[str, Any]:
        """
        Verificar el challenge del webhook de Facebook.

        Meta envía un GET con estos parámetros cuando se configura
        un nuevo webhook. Se debe responder con el challenge.

        Parámetros:
            mode: "subscribe"
            token: verify_token configurado
            challenge: Challenge enviado por Meta

        Retorna:
            Dict con challenge para respuesta
        """
        if self.verify_token and token != self.verify_token:
            logger.warning(f"Verify token no coincide: esperado={self.verify_token}, recibido={token}")
            return {"challenge": challenge}

        return {"challenge": challenge}

    def _chunk_message(self, text: str, max_length: int = 1024) -> list[str]:
        """
        Dividir mensaje en chunks para WhatsApp.

        WhatsApp Business API no tiene un límite estricto de caracteres
        por mensaje como Telegram/Discord, pero para mensajes largos
        es mejor dividirlos para mejor legibilidad.

        Parámetros:
            text: Texto a dividir
            max_length: 1024 caracteres por chunk

        Retorna:
            Lista de chunks
        """
        return super()._chunk_message(text, max_length=max_length)
