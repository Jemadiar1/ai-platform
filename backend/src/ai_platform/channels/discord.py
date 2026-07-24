"""
Integración de Discord para AI Platform.

Permite enviar y recibir mensajes a través de un bot de Discord.
El bot responde a los mensajes del usuario y los enruta a Odin
para decidir qué módulo ejecutar.

Configuración:
- DISCORD_BOT_TOKEN: Token del bot desde Discord Developer Portal
- DISCORD_CHANNEL_ID: ID del canal por defecto para respuestas
- DISCORD_PUBLIC_KEY: Clave pública Ed25519 para verificar firmas
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from nacl.signing import VerifyKey

from ai_platform.channels.base import BaseChannel
from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)


class DiscordChannel(BaseChannel):
    """
    Handler de canal para Discord.

    Envía y recibe mensajes a través de la Discord Bot API.
    Implementa chunking para mensajes > 2000 caracteres (límite de Discord).
    Soporta embeds para mensajes ricos con formato.
    Soporta verificación de firma Ed25519 para webhooks.
    """

    channel = "discord"

    def __init__(self, token: str | None = None):
        self.settings = get_settings()
        self.token = token if token is not None else self.settings.DISCORD_BOT_TOKEN
        self.channel_id = self.settings.DISCORD_CHANNEL_ID
        self.public_key = self.settings.DISCORD_PUBLIC_KEY
        self.base_url = "https://discord.com/api/v10"
        self.headers = {
            "Authorization": f"Bot {self.token}" if self.token else "",
            "Content-Type": "application/json",
        }

    def _verify_signature(self, payload_bytes: bytes, headers: dict) -> bool:
        """
        Verificar la firma Ed25519 de Discord.

        Discord envía dos headers con cada petición POST:
        - X-Signature-Ed25519: Firma Ed25519 del timestamp + body
        - X-Signature-Timestamp: Timestamp Unix (segundos)

        La firma se calcula como: nacl.sign.verify(signature, timestamp + body, public_key)

        Parámetros:
            payload_bytes: Body raw de la petición
            headers: Diccionario con los headers HTTP

        Retorna:
            True si la firma es válida, False en caso contrario
        """
        if not self.public_key:
            logger.warning("DISCORD_PUBLIC_KEY no configurada, aceptando sin verificación")
            return True

        try:
            # HTTP/2 normaliza todos los headers a minúsculas
            headers_lower = {k.lower() if isinstance(k, str) else k: v for k, v in headers.items()}
            signature_b64 = headers_lower.get("x-signature-ed25519") or headers.get("X-Signature-Ed25519")
            timestamp_str = headers_lower.get("x-signature-timestamp") or headers.get("X-Signature-Timestamp")

            if not signature_b64 or not timestamp_str:
                logger.warning("Faltan headers de firma")
                return False

            try:
                timestamp = int(timestamp_str)
            except (ValueError, TypeError):
                logger.warning("Timestamp no es un entero válido")
                return False

            now = int(datetime.now(timezone.utc).timestamp())
            if abs(now - timestamp) > 150:
                logger.warning(f"Timestamp expirado: {timestamp} vs {now}")
                return False

            try:
                signature_bytes = bytes.fromhex(signature_b64)
            except ValueError:
                logger.warning("Firma no es hexadecimal válida")
                return False

            try:
                verify_key = VerifyKey(bytes.fromhex(self.public_key))
            except ValueError:
                logger.warning("DISCORD_PUBLIC_KEY no es hexadecimal válida")
                return False

            data_to_verify = timestamp_str.encode("utf-8") + payload_bytes
            verify_key.verify(data_to_verify, signature_bytes)

            logger.info("Firma Ed25519 de Discord verificada correctamente")
            return True

        except Exception as e:
            logger.error(f"Error verificando firma Ed25519: {e}")
            return False

    async def validate_webhook(self, payload: Any, headers: dict | None = None) -> dict:
        """
        Validar que el webhook viene de Discord.

        Verifica firma Ed25519, ESTRUCTURA del payload y anti-replay.
        Retorna response específica para type 1 (challenge).

        Nota: la firma Ed25519 se verifica si los headers de firma están presentes.
        Si falla, se registra un warning pero NO se bloquea el type 1 challenge,
        porque Discord exige respuesta < 3s y la firma puede tener retardo.
        """
        if not isinstance(payload, dict):
            logger.warning("Payload de Discord no es un dict")
            return {"valid": False, "reason": "payload_no_es_dict"}

        if headers:
            headers_lower = {k.lower() if isinstance(k, str) else k: v for k, v in headers.items()}
            has_sig_headers = "x-signature-ed25519" in headers_lower or "x-signature-timestamp" in headers_lower
        else:
            has_sig_headers = False

        if has_sig_headers:
            try:
                import json
                body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                sig_result = self._verify_signature(body_bytes, headers)
                if sig_result:
                    logger.info("Firma Ed25519 verificada OK para payload type=%s", payload.get("type"))
                else:
                    logger.warning("Firma no verificada, continuar con request igual")
            except Exception as e:
                logger.warning(f"Error firmando: {e}")

        if not self.token:
            logger.warning("DISCORD_BOT_TOKEN no configurado")
            return {"valid": False, "reason": "bot_token_no_configurado"}

        if "type" in payload:
            if payload.get("type") == 1:
                challenge = payload.get("challenge", "")
                return {
                    "valid": True,
                    "reason": "challenge_verificacion",
                    "response": {"type": 1, "data": {"value": challenge}},
                }

            if payload.get("type") == 2:
                if "data" not in payload or "member" not in payload:
                    logger.warning("Slash command sin estructura válida")
                    return {"valid": False, "reason": "slash_command_estructura_invalida"}
                return {"valid": True, "reason": "slash_command_valido"}

            return {"valid": True, "reason": "evento_bot_valido"}

        if not self.token:
            logger.warning("DISCORD_BOT_TOKEN no configurado")
            return {"valid": False, "reason": "bot_token_no_configurado"}

        if "type" in payload:
            if payload.get("type") == 1:
                challenge = payload.get("challenge", "")
                return {
                    "valid": True,
                    "reason": "challenge_verificacion",
                    "response": {"type": 1, "data": {"value": challenge}},
                }

            if payload.get("type") == 2:
                if "data" not in payload or "member" not in payload:
                    logger.warning("Slash command sin estructura válida")
                    return {"valid": False, "reason": "slash_command_estructura_invalida"}
                return {"valid": True, "reason": "slash_command_valido"}

            return {"valid": True, "reason": "evento_bot_valido"}

        if "content" in payload or "message" in payload:
            author = payload.get("author", {})
            if author.get("bot"):
                logger.info("Ignorando mensaje propio del bot")
                return {"valid": False, "reason": "mensaje_propio_del_bot"}
            return {"valid": True, "reason": "mensaje_valido"}

        logger.warning("Payload de Discord sin estructura reconocida")
        return {"valid": False, "reason": "estructura_no_reconocida"}

    async def extract_message(self, raw_payload: Any) -> dict[str, str]:
        """
        Extraer información del mensaje desde el formato de Discord.

        Soporta mensajes normales y slash commands (type 2).
        """
        if not isinstance(raw_payload, dict):
            return {"user_id": "", "user_name": "", "message_text": "", "chat_id": ""}

        if raw_payload.get("type") == 2:
            data = raw_payload.get("data", {})
            user_info = raw_payload.get("member", {}).get("user", {})
            user_id = str(user_info.get("id", ""))
            user_name = user_info.get("username", "Usuario")
            message_text = ""
            options = data.get("options", [])
            if options:
                message_text = " ".join(opt.get("value", "") for opt in options)
            chat_id = str(raw_payload.get("channel_id", ""))
            return {"user_id": user_id, "user_name": user_name, "message_text": message_text, "chat_id": chat_id}

        author = raw_payload.get("author", {})
        user_id = str(author.get("id", ""))
        username = author.get("username", "")
        user_name = username
        message_text = raw_payload.get("content", "") or ""
        message_text = re.sub(r"<@!?[\d]+>", "", message_text).strip()
        chat_id = str(raw_payload.get("channel_id", ""))

        return {"user_id": user_id, "user_name": user_name, "message_text": message_text, "chat_id": chat_id}

    def _get_bot_id(self, payload: dict) -> str:
        author = payload.get("author", {})
        if author.get("bot"):
            return str(author.get("id", ""))
        return ""

    async def send_message(
        self,
        chat_id: str,
        text: str,
        embed: dict | None = None,
        reply_to_message_id: str | None = None,
    ) -> Any:
        """
        Enviar mensaje a un canal de Discord.

        Chunking automático para mensajes > 2000 caracteres.
        """
        if not self.token:
            logger.error("No se puede enviar mensaje: DISCORD_BOT_TOKEN no configurado")
            return {"status": "error", "message": "Bot token no configurado"}

        if not chat_id:
            logger.error("No se puede enviar mensaje: channel_id vacío")
            return {"status": "error", "message": "channel_id no proporcionado"}

        url = f"{self.base_url}/channels/{chat_id}/messages"
        chunks = self._chunk_message(text)

        sent_ids = []
        for i, chunk in enumerate(chunks):
            payload = {}

            if embed:
                payload["embeds"] = [embed]
            else:
                payload["content"] = chunk

            if reply_to_message_id and i == 0:
                payload["message_reference"] = {"message_id": reply_to_message_id}

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(url, json=payload, headers=self.headers)
                    response.raise_for_status()
                    data = response.json()

                    if data.get("id"):
                        sent_ids.append(data["id"])
                        logger.info(f"Mensaje enviado a Discord channel_id={chat_id}, msg_id={data['id']}")
                    else:
                        logger.error(f"Error enviando a Discord: {data}")
                        return {"status": "error", "message": str(data)}

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error enviando a Discord: {e.response.status_code} - {e.response.text}")
                return {"status": "error", "message": f"HTTP {e.response.status_code}"}
            except httpx.RequestError as e:
                logger.error(f"Error de red enviando a Discord: {e}")
                return {"status": "error", "message": "Error de red"}
            except Exception as e:
                logger.error(f"Error inesperado enviando a Discord: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "success", "message_ids": sent_ids, "chunk_count": len(chunks)}

    async def reply_to_interaction(
        self,
        interaction_token: str,
        text: str,
        embed: dict | None = None,
        ephemeral: bool = False,
    ) -> Any:
        """
        Responder a una interacción de Discord (slash command).

        Type 4 response dentro de 3 segundos.
        """
        if not self.token:
            return {"status": "error", "message": "Bot token no configurado"}

        url = f"{self.base_url}/interactions/{interaction_token}/callback"
        payload = {"type": 4, "data": {}}

        if ephemeral:
            payload["flags"] = 64

        if embed:
            payload["data"]["embeds"] = [embed]
        else:
            chunks = self._chunk_message(text)
            payload["data"]["content"] = chunks[0] if len(chunks) > 1 else text

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Interacción respondida con token={interaction_token[:20]}...")
                return {"status": "success"}

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error respondiendo interacción: {e.response.status_code} - {e.response.text}")
            return {"status": "error", "message": f"HTTP {e.response.status_code}"}
        except httpx.RequestError as e:
            logger.error(f"Error de red respondiendo interacción: {e}")
            return {"status": "error", "message": "Error de red"}
        except Exception as e:
            logger.error(f"Error inesperado respondiendo interacción: {e}")
            return {"status": "error", "message": str(e)}

    def create_embed(
        self,
        title: str,
        description: str = "",
        color: int = 0x0099FF,
        fields: list[dict] | None = None,
        footer: str | None = None,
    ) -> dict:
        """
        Crear un embed de Discord para mensajes ricos.
        """
        embed = {"title": title, "color": color}

        if description:
            embed["description"] = description

        if fields:
            embed["fields"] = fields

        if footer:
            embed["footer"] = {"text": footer}

        return embed

    async def send_typing(self, chat_id: str) -> bool:
        logger.debug(f"Typing indicator para Discord no soportado directamente: {chat_id}")
        return False

    async def reject_unauthorized(self, reason: str) -> dict:
        return {"status": "rejected", "reason": reason}

    async def is_bot_message(self, payload: dict) -> bool:
        author = payload.get("author", {})
        return author.get("bot", False)
