"""
Integración de Discord para AI Platform.

Permite enviar y recibir mensajes a través de un bot de Discord.
El bot responde a los mensajes del usuario y los enruta a Odin
para decidir qué módulo ejecutar.

Configuración:
- DISCORD_BOT_TOKEN: Token del bot desde Discord Developer Portal
- DISCORD_CHANNEL_ID: ID del canal por defecto para respuestas

"""

import logging
import re
from typing import Any

import httpx

from ai_platform.channels.base import BaseChannel
from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)


class DiscordChannel(BaseChannel):
    """
    Handler de canal para Discord.

    Envía y recibe mensajes a través de la Discord Bot API.
    Implementa chunking para mensajes > 2000 caracteres (límite de Discord).
    Soporta embeds para mensajes ricos con formato.
    """

    channel = "discord"

    def __init__(self, token: str | None = None):
        self.settings = get_settings()
        self.token = token if token is not None else self.settings.DISCORD_BOT_TOKEN
        self.channel_id = self.settings.DISCORD_CHANNEL_ID
        self.base_url = "https://discord.com/api/v10"
        self.headers = {
            "Authorization": f"Bot {self.token}" if self.token else "",
            "Content-Type": "application/json",
        }

    async def validate_webhook(self, payload: Any, headers: dict | None = None) -> dict:
        """
        Validar que el webhook viene de Discord.

        Para webhooks de Discord, se verifica que el token esté configurado
        y que el payload tenga la estructura esperada.
        Para eventos de bot (gateway), se verifica que el autor no sea el bot
        mismo para prevenir bucles de eco.

        Parámetros:
            payload: Payload del webhook/evento de Discord
            headers: Diccionario con los headers HTTP (opcional)

        Retorna:
            Dict con claves:
                - valid: bool, si el webhook es válido
                - reason: str, razón de invalidación si aplica
        """
        if not isinstance(payload, dict):
            logger.warning("Payload de Discord no es un dict")
            return {"valid": False, "reason": "payload_no_es_dict"}

        # Verificar que el token del bot esté configurado
        if not self.token:
            logger.warning("DISCORD_BOT_TOKEN no configurado, rechazando webhook")
            return {"valid": False, "reason": "bot_token_no_configurado"}

        # Verificar estructura básica del evento
        if "type" in payload:
            # Type 1 es el challenge de verificación de webhook de Discord
            if payload.get("type") == 1:
                return {"valid": True, "reason": "challenge_verificacion"}

            # Type 2 es un slash command / interacción
            if payload.get("type") == 2:
                # Validar que tenga data y member (estructura de slash command)
                if "data" not in payload or "member" not in payload:
                    logger.warning("Payload de slash command sin estructura válida")
                    return {"valid": False, "reason": "slash_command_estructura_invalida"}
                return {"valid": True, "reason": "slash_command_valido"}

            # Otros tipos de eventos (message_create, message_update, etc.)
            # Tienen un type numérico pero no son webhooks HTTP tradicionales
            # Son eventos del gateway del bot
            return {"valid": True, "reason": "evento_bot_valido"}

        # Si tiene estructura de mensaje, es válido
        if "content" in payload or "message" in payload:
            # Prevenir bucles de eco: verificar que el autor no sea el bot
            author = payload.get("author", {})
            if author.get("bot"):
                logger.info("Ignorando mensaje propio del bot para prevenir eco")
                return {"valid": False, "reason": "mensaje_propio_del_bot"}
            return {"valid": True, "reason": "mensaje_valido"}

        logger.warning("Payload de Discord sin estructura reconocida")
        return {"valid": False, "reason": "estructura_no_reconocida"}

    async def extract_message(self, raw_payload: Any) -> dict[str, str]:
        """
        Extraer información del mensaje desde el formato de Discord.

        Formato de entrada (gateway message):
        {
            "id": "message_id",
            "content": "Hola, necesito ayuda",
            "author": {
                "id": "user_id",
                "username": "Juan",
                "discriminator": "1234"
            },
            "channel_id": "channel_id",
            "guild_id": "guild_id",
            "timestamp": "2026-05-07T20:00:00.000000+00:00"
        }

        Formato de entrada (slash command):
        {
            "type": 2,
            "data": {
                "name": "ask",
                "options": [...]
            },
            "member": {
                "user": {
                    "id": "user_id",
                    "username": "Juan"
                }
            },
            "channel_id": "channel_id"
        }

        Parámetros:
            raw_payload: Evento de Discord

        Retorna:
            {
                "user_id": "user_id",
                "user_name": "Juan",
                "message_text": "Hola, necesito ayuda",
                "chat_id": "channel_id"
            }
        """
        if not isinstance(raw_payload, dict):
            return {
                "user_id": "",
                "user_name": "",
                "message_text": "",
                "chat_id": "",
            }

        # Detectar si es un slash command
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

            return {
                "user_id": user_id,
                "user_name": user_name,
                "message_text": message_text,
                "chat_id": chat_id,
            }

        # Mensaje normal
        author = raw_payload.get("author", {})
        user_id = str(author.get("id", ""))
        username = author.get("username", "")
        user_name = username  # No incluir discriminator en nombre

        message_text = raw_payload.get("content", "") or ""

        # Eliminar menciones del bot del mensaje (<@ID> y <@!ID>)
        message_text = re.sub(r"<@!?[\d]+>", "", message_text).strip()

        chat_id = str(raw_payload.get("channel_id", ""))

        return {
            "user_id": user_id,
            "user_name": user_name,
            "message_text": message_text,
            "chat_id": chat_id,
        }

    def _get_bot_id(self, payload: dict) -> str:
        """
        Extraer el ID del bot del payload.

        Parámetros:
            payload: Payload de Discord

        Retorna:
            ID del bot como string, o cadena vacía si no se puede determinar
        """
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

        Usa la API sendMessage de Discord.
        Soporta embeds para mensajes ricos con formato.

        Parámetros:
            chat_id: ID del canal de Discord
            text: Contenido del mensaje
            embed: Embed para mensajes ricos (opcional)
            reply_to_message_id: ID del mensaje al que responder (opcional)

        Retorna:
            Dict con resultado de la API (id, etc.)
        """
        if not self.token:
            logger.error("No se puede enviar mensaje: DISCORD_BOT_TOKEN no configurado")
            return {"status": "error", "message": "Bot token no configurado"}

        if not chat_id:
            logger.error("No se puede enviar mensaje: channel_id vacío")
            return {"status": "error", "message": "channel_id no proporcionado"}

        url = f"{self.base_url}/channels/{chat_id}/messages"

        payload = {}

        if embed:
            payload["embeds"] = [embed]
        else:
            payload["content"] = text

        if reply_to_message_id:
            payload["message_reference"] = {
                "message_id": reply_to_message_id,
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self.headers,
                )
                response.raise_for_status()
                data = response.json()

                if data.get("id"):
                    logger.info(f"Mensaje enviado a Discord channel_id={chat_id}")
                    return data
                else:
                    logger.error(f"Error enviando a Discord: {data}")
                    return {"status": "error", "message": str(data)}

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error enviando mensaje a Discord: {e.response.status_code} - {e.response.text}")
            return {"status": "error", "message": f"HTTP {e.response.status_code}"}
        except httpx.RequestError as e:
            logger.error(f"Error de red enviando mensaje a Discord: {e}")
            return {"status": "error", "message": "Error de red"}
        except Exception as e:
            logger.error(f"Error inesperado enviando mensaje a Discord: {e}")
            return {"status": "error", "message": str(e)}

    async def reply_to_interaction(
        self,
        interaction_token: str,
        text: str,
        embed: dict | None = None,
        ephemeral: bool = False,
    ) -> Any:
        """
        Responder a una interacción de Discord (slash command).

        Parámetros:
            interaction_token: Token de la interacción
            text: Contenido de la respuesta
            embed: Embed opcional
            ephemeral: Si True, mensaje visible solo para el usuario

        Retorna:
            Dict con resultado de la API
        """
        if not self.token:
            return {"status": "error", "message": "Bot token no configurado"}

        url = f"{self.base_url}/interactions/{interaction_token}/callback"

        payload = {
            "type": 4,
            "data": {},
        }

        if embed:
            payload["data"]["embeds"] = [embed]
        else:
            payload["data"]["content"] = text

        if ephemeral:
            payload["data"]["flags"] = 64  # EPHEMERAL flag

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self.headers,
                )
                response.raise_for_status()
                return {"status": "success"}
        except Exception as e:
            logger.error(f"Error respondiendo interacción de Discord: {e}")
            return {"status": "error", "message": str(e)}

    def _chunk_message(self, text: str, max_length: int = 2000) -> list[str]:
        """
        Dividir mensaje en chunks de máximo 2000 caracteres (límite de Discord).

        Sobrescribe el método base para usar el límite correcto de Discord.

        Parámetros:
            text: Texto a dividir
            max_length: 2000 (límite de Discord)

        Retorna:
            Lista de chunks
        """
        return super()._chunk_message(text, max_length=max_length)

    @staticmethod
    def create_embed(
        title: str,
        description: str = "",
        color: int = 0x0099FF,
        fields: list[dict] | None = None,
        footer: str | None = None,
    ) -> dict:
        """
        Crear un embed para mensajes ricos de Discord.

        Parámetros:
            title: Título del embed
            description: Descripción del embed
            color: Color en hexadecimal (default: azul)
            fields: Lista de campos {name, value, inline}
            footer: Texto del pie

        Retorna:
            Dict con formato de embed de Discord
        """
        embed = {
            "title": title,
            "color": color,
        }

        if description:
            embed["description"] = description

        if fields:
            embed["fields"] = fields

        if footer:
            embed["footer"] = {"text": footer}

        return embed
