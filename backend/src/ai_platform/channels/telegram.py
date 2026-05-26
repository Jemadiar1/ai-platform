"""
Integración de Telegram para AI Platform.

Permite enviar y recibir mensajes a través de un bot de Telegram.
El bot responde a los mensajes del usuario y los enruta a Odin
para decidir qué módulo ejecutar.

Configuración:
- TELEGRAM_BOT_TOKEN: Token del bot desde @BotFather
- Se usa formato MarkdownHTML para formateo de texto

"""

import logging
from typing import Any

import httpx

from ai_platform.channels.base import BaseChannel
from ai_platform.core.config import get_settings

logger = logging.getLogger(__name__)


class TelegramChannel(BaseChannel):
    """
    Handler de canal para Telegram.

    Envía y recibe mensajes a través de la Telegram Bot API.
    Implementa chunking para mensajes > 4096 caracteres (límite de Telegram).

    Configuración:
    - TELEGRAM_BOT_TOKEN: Token del bot desde @BotFather (para enviar mensajes)
    - TELEGRAM_WEBHOOK_SECRET: Secret token para validar webhooks entrantes
      (configurable en @BotFather -> Set Webhook -> Set Secret Token)
    """

    channel = "telegram"

    def __init__(
        self,
        token: str | None = None,
        webhook_secret: str | None = None,
    ):
        self.settings = get_settings()
        self.token = token if token is not None else self.settings.TELEGRAM_BOT_TOKEN
        self.webhook_secret = webhook_secret if webhook_secret is not None else self.settings.TELEGRAM_WEBHOOK_SECRET
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    async def validate_webhook(self, payload: Any, headers: dict | None = None) -> dict:
        """
        Validar que el webhook viene de Telegram.

        Verifica:
        1. El secret token del header X-Telegram-Bot-Api-Secret-Token
           (configurado en @BotFather -> Set Webhook -> Set Secret Token)
        2. Que el update tenga update_id válido
        3. Que el mensaje no sea de un bot (para prevenir eco)

        Parámetros:
            payload: Dict con el update de Telegram
            headers: Diccionario con los headers HTTP (opcional)

        Retorna:
            Dict con claves:
                - valid: bool, si el webhook es válido
                - reason: str, razón de invalidación si aplica
        """
        if not isinstance(payload, dict):
            logger.warning("Payload de Telegram no es un dict")
            return {"valid": False, "reason": "payload_no_es_dict"}

        # Verificar secret token del header X-Telegram-Bot-Api-Secret-Token
        # Este secret es independiente del bot token y se configura en BotFather
        if headers and self.webhook_secret:
            secret_token = headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if secret_token and secret_token != self.webhook_secret:
                logger.warning("X-Telegram-Bot-Api-Secret-Token no coincide")
                return {"valid": False, "reason": "secret_token_no_coincide"}

        # Verificar estructura básica: un update debe tener 'update_id' y 'message' o 'edited_message'
        update_id = payload.get("update_id")
        if not update_id:
            logger.warning("Update sin update_id")
            return {"valid": False, "reason": "sin_update_id"}

        # Verificar que el mensaje no sea de un bot (para prevenir eco)
        message = payload.get("message") or payload.get("edited_message") or payload.get("channel_post")
        if message:
            is_bot = message.get("from", {}).get("is_bot")
            if is_bot:
                logger.info("Ignorando mensaje de bot")
                return {"valid": False, "reason": "mensaje_de_bot"}

        return {"valid": True, "reason": "webhook_valido"}

    async def extract_message(self, raw_payload: Any) -> dict[str, str]:
        """
        Extraer información del mensaje desde el formato Bot API de Telegram.

        Formato de entrada:
        {
            "update_id": 123456,
            "message": {
                "message_id": 789,
                "text": "Hola, necesito ayuda",
                "from": {
                    "id": 111222,
                    "first_name": "Juan",
                    "username": "juanperez"
                },
                "chat": {
                    "id": 111222,
                    "type": "private"
                },
                "date": 1234567890
            }
        }

        Parámetros:
            raw_payload: Update de Telegram

        Retorna:
            {
                "user_id": "111222",
                "user_name": "Juan",
                "message_text": "Hola, necesito ayuda",
                "chat_id": "111222"
            }
        """
        if not isinstance(raw_payload, dict):
            return {
                "user_id": "",
                "user_name": "",
                "message_text": "",
                "chat_id": "",
            }

        message = raw_payload.get("message") or raw_payload.get("edited_message") or raw_payload.get("channel_post")
        if not message:
            return {
                "user_id": "",
                "user_name": "",
                "message_text": "",
                "chat_id": "",
            }

        # Extraer información del usuario
        user_info = message.get("from", {})
        user_id = str(user_info.get("id", ""))
        first_name = user_info.get("first_name", "")
        username = user_info.get("username", "")
        user_name = first_name or username or "Usuario"

        # Extraer chat_id (para responder)
        chat_info = message.get("chat", {})
        chat_id = str(chat_info.get("id", ""))

        # Extraer texto del mensaje
        message_text = message.get("text", "") or message.get("caption", "")

        return {
            "user_id": user_id,
            "user_name": user_name,
            "message_text": message_text,
            "chat_id": chat_id,
        }

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
    ) -> Any:
        """
        Enviar mensaje a un chat de Telegram.

        Usa la API sendMessage de Telegram.
        Soporta parse_mode HTML y reply_markup para botones interactivos.

        Parámetros:
            chat_id: ID del chat de Telegram
            text: Contenido del mensaje
            parse_mode: Formato de texto ("HTML" o "MarkdownV2")
            reply_markup: Botones del bot (KeyboardMarkup/InlineKeyboardMarkup)

        Retorna:
            Dict con resultado de la API (message_id, etc.)
        """
        if not self.token:
            logger.error("No se puede enviar mensaje: TELEGRAM_BOT_TOKEN no configurado")
            return {"status": "error", "message": "Bot token no configurado"}

        if not chat_id:
            logger.error("No se puede enviar mensaje: chat_id vacío")
            return {"status": "error", "message": "chat_id no proporcionado"}

        url = f"{self.base_url}/sendMessage"

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()

                if data.get("ok"):
                    logger.info(f"Mensaje enviado a Telegram chat_id={chat_id}")
                    return data
                else:
                    logger.error(f"Error enviando a Telegram: {data}")
                    return {"status": "error", "message": data.get("description", "Error desconocido")}

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error enviando mensaje a Telegram: {e.response.status_code} - {e.response.text}")
            return {"status": "error", "message": f"HTTP {e.response.status_code}"}
        except httpx.RequestError as e:
            logger.error(f"Error de red enviando mensaje a Telegram: {e}")
            return {"status": "error", "message": "Error de red"}
        except Exception as e:
            logger.error(f"Error inesperado enviando mensaje a Telegram: {e}")
            return {"status": "error", "message": str(e)}

    async def send_answer(
        self,
        callback_query_id: str,
        text: str,
        show_alert: bool = False,
    ) -> Any:
        """
        Responder a una callback query (botones inline).

        Se usa cuando el usuario presiona un botón inline del bot.

        Parámetros:
            callback_query_id: ID de la callback query
            text: Texto a mostrar al usuario
            show_alert: Si True, muestra como alerta emergente

        Retorna:
            Dict con resultado de la API
        """
        if not self.token:
            return {"status": "error", "message": "Bot token no configurado"}

        url = f"{self.base_url}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data
        except Exception as e:
            logger.error(f"Error respondiendo callback query: {e}")
            return {"status": "error", "message": str(e)}

    def _chunk_message(self, text: str, max_length: int = 4096) -> list[str]:
        """
        Dividir mensaje en chunks de máximo 4096 caracteres (límite de Telegram).

        Sobrescribe el método base para usar el límite correcto de Telegram.

        Parámetros:
            text: Texto a dividir
            max_length: 4096 (límite de Telegram)

        Retorna:
            Lista de chunks
        """
        return super()._chunk_message(text, max_length=max_length)


def create_telegram_keyboard(buttons: list[list[str]], url: str | None = None) -> dict:
    """
    Crear un teclado personalizado para Telegram.

    Parámetros:
        buttons: Lista de filas, cada fila es una lista de botones
        url: URL opcional para InlineKeyboardButton (web app)

    Retorna:
        Dict con formato Telegram KeyboardMarkup
    """
    keyboard = []
    for row in buttons:
        keyboard_row = []
        for label in row:
            if url:
                keyboard_row.append(
                    {
                        "text": label,
                        "url": url,
                    }
                )
            else:
                keyboard_row.append(
                    {
                        "text": label,
                        "callback_data": label,
                    }
                )
        keyboard.append(keyboard_row)

    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


# Mapeo de reacciones emoji a ratings para feedback
REACTION_RATING_MAP: dict[str, int] = {
    "emoji_thumbs_up": 3,
    "emoji_thumbs_down": 1,
    "emoji_heart": 3,
    "emoji_fire": 3,
    "emoji_star": 3,
}


class TelegramReactionHandler:
    """
    Manejador de reacciones de Telegram para feedback.

    Mapea reacciones emoji a ratings numéricos (1-3)
    que se registran en el sistema de feedback.
    """

    def __init__(self, bot_token: str | None = None):
        self.settings = get_settings()
        self.token = bot_token or self.settings.TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    def handle_reaction(self, reaction: dict[str, Any]) -> dict[str, Any]:
        """
        Manejar una reacción a un mensaje del bot.

        Parámetros:
            reaction: Dict con estructura de message_reaction de Telegram

        Retorna:
            Dict con resultado del manejo de reacción
        """
        message = reaction.get("message", {})
        chat = message.get("chat", {})
        user = reaction.get("user", {})
        reaction_obj = reaction.get("reaction", [{}])[0] if reaction.get("reaction") else {}

        reaction_type = reaction_obj.get("type", {}).get("name", "") if reaction_obj.get("type") else ""
        rating = REACTION_RATING_MAP.get(reaction_type)

        if rating is None:
            return {"status": "ignored", "reaction": reaction_type}

        chat_id = str(chat.get("id", ""))
        user_id = str(user.get("id", ""))

        logger.info(f"Reaction feedback: user={user_id}, chat={chat_id}, reaction={reaction_type}, rating={rating}")

        return {
            "status": "recorded",
            "reaction": reaction_type,
            "rating": rating,
            "user_id": user_id,
            "chat_id": chat_id,
        }

    def handle_command(self, message_text: str, chat_id: str, user_id: str) -> dict[str, Any]:
        """
        Manejar comandos slash (/rate up, /rate down, etc.).

        Parámetros:
            message_text: Texto completo del mensaje del usuario
            chat_id: ID del chat
            user_id: ID del usuario

        Retorna:
            Dict con resultado del manejo del comando
        """
        parts = message_text.strip().split()
        if not parts:
            return {"status": "ignored"}

        command = parts[0].lower()

        if command == "/rate":
            rating_str = parts[1].lower() if len(parts) > 1 else ""
            if rating_str in ("up", "\U0001f44d", "+"):
                return {
                    "status": "recorded",
                    "rating": 3,
                    "response": "Feedback registrado: \U0001f44d \u00a1Gracias!",
                }
            elif rating_str in ("down", "\U0001f44e", "-"):
                return {
                    "status": "recorded",
                    "rating": 1,
                    "response": "Feedback registrado: \U0001f44e Lo sentimos. Mejoremos.",
                }
            else:
                return {
                    "status": "recorded",
                    "rating": 2,
                    "response": "Usa: /rate up o /rate down para calificar respuestas de Od\u00edn.",
                }

        return {"status": "ignored"}
