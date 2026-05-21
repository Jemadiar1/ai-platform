"""
Paquete de canales - Integraciones con Telegram, Discord y WhatsApp.

Cada canal implementa la misma interfaz:
1. validate_webhook(payload) → validar autenticidad
2. extract_message(raw_payload) → {channel, user_id, user_name, message_text, chat_id}
3. handle_webhook(raw_payload) → flujo completo: extraer → Odin → enviar respuesta
4. send_message(chat_id, text) → enviar respuesta al canal

"""

from ai_platform.channels.base import BaseChannel
from ai_platform.channels.discord import DiscordChannel
from ai_platform.channels.telegram import TelegramChannel
from ai_platform.channels.whatsapp_channel import WhatsAppChannel

__all__ = [
    "BaseChannel",
    "DiscordChannel",
    "TelegramChannel",
    "WhatsAppChannel",
]
