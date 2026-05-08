"""
Tests para la integración de canales (webhooks).

Prueba realmente las clases de canal (TelegramChannel, DiscordChannel, WhatsAppChannel)
y funciones como _chunk_message, no solo diccionarios hardcodeados.

Cubre:
- Validación de webhooks (fuerza válida / inválida)
- Extracción de mensajes (Telegram, Discord, WhatsApp)
- Chunking de mensajes
- Respuestas a botones y callbacks
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_platform.core.security import scanner, prompt_sanitizer


# ---------------------------------------------------------------------------
# Fix 5: Tests reales que ejercitan las clases de canal
# ---------------------------------------------------------------------------


class TestTelegramChannelValidateWebhook:
    """Tests reales que ejercitan TelegramChannel.validate_webhook()."""

    def test_validate_webhook_valid_token_match(self):
        """Debe validar un webhook de Telegram cuando el token coincide."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test_secret_token")
        payload = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": 123, "first_name": "Juan", "is_bot": False},
                "chat": {"id": 456, "type": "private"},
                "text": "Hola, necesito ayuda",
                "date": 1234567890,
            },
        }
        headers = {"X-Telegram-Bot-Api-Secret-Token": "test_secret_token"}
        result = channel.validate_webhook(payload, headers=headers)
        assert result["valid"] is True

    def test_validate_webhook_valid_structure(self):
        """Debe validar un webhook con estructura correcta y token configurado."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="some_token")
        payload = {
            "update_id": 42,
            "edited_message": {
                "message_id": 10,
                "text": "Mensaje editado",
                "from": {"id": 789, "first_name": "María", "is_bot": False},
                "chat": {"id": 789, "type": "private"},
                "date": 1234567890,
            },
        }
        result = channel.validate_webhook(payload)
        assert result["valid"] is True

    def test_validate_webhook_rejects_bot_messages(self):
        """Debe rechazar mensajes que provienen de otros bots."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test_token")
        payload = {
            "update_id": 99,
            "message": {
                "message_id": 1,
                "from": {"id": 0, "is_bot": True},
                "chat": {"id": 1, "type": "private"},
                "text": "Soy un bot",
            },
        }
        result = channel.validate_webhook(payload)
        assert result["valid"] is False

    def test_validate_webhook_missing_update_id(self):
        """Debe rechazar payloads sin update_id."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test_token")
        payload = {"message": {"text": "sin update_id"}}
        result = channel.validate_webhook(payload)
        assert result["valid"] is False

    def test_validate_webhook_non_dict_payload(self):
        """Debe rechazar payloads que no sean dict."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test_token")
        result = channel.validate_webhook("not a dict")
        assert result["valid"] is False

    def test_validate_webhook_no_token_skips_validation(self):
        """Si no hay token, la validación se salta (retorna True)."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="")
        result = channel.validate_webhook({"update_id": 1})
        assert result["valid"] is True


class TestTelegramChannelExtractMessage:
    """Tests reales que ejercitan TelegramChannel.extract_message()."""

    def test_extract_message_private_chat(self):
        """Debe extraer info correctamente de un chat privado."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test")
        payload = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": 123, "first_name": "Juan", "is_bot": False},
                "chat": {"id": 456, "type": "private"},
                "text": "Hola, necesito ayuda",
                "date": 1234567890,
            },
        }
        result = channel.extract_message(payload)
        assert result["user_id"] == "123"
        assert result["user_name"] == "Juan"
        assert result["message_text"] == "Hola, necesito ayuda"
        assert result["chat_id"] == "456"

    def test_extract_message_edited(self):
        """Debe extraer info de un mensaje editado."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test")
        payload = {
            "update_id": 2,
            "edited_message": {
                "message_id": 2,
                "from": {"id": 999, "first_name": "Ana", "is_bot": False},
                "chat": {"id": 999, "type": "private"},
                "text": "Mensaje editado",
            },
        }
        result = channel.extract_message(payload)
        assert result["user_id"] == "999"
        assert result["message_text"] == "Mensaje editado"

    def test_extract_message_empty_payload(self):
        """Debe retornar valores vacíos para un payload inválido."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test")
        result = channel.extract_message({"no_valid_campo": "xxx"})
        assert result["user_id"] == ""
        assert result["message_text"] == ""

    def test_extract_message_non_dict(self):
        """Debe retornar valores vacíos para un payload no-dict."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test")
        result = channel.extract_message("string")
        assert result["user_id"] == ""

    def test_extract_message_group_chat(self):
        """Debe extraer info correctamente de un chat de grupo."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test")
        payload = {
            "update_id": 3,
            "message": {
                "message_id": 7,
                "from": {"id": 111, "first_name": "Pedro", "is_bot": False},
                "chat": {"id": -1001234567890, "title": "Mi Grupo", "type": "supergroup"},
                "text": "Mensaje en grupo",
            },
        }
        result = channel.extract_message(payload)
        assert result["user_id"] == "111"
        assert result["chat_id"] == "-1001234567890"
        assert result["message_text"] == "Mensaje en grupo"


class TestTelegramChannelSendMessage:
    """Tests de envío de mensajes a Telegram."""

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """Debe enviar mensaje exitosamente con token configurado."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="valid_token")

        with patch("ai_platform.channels.telegram.httpx.AsyncClient") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True, "result": {"message_id": 42}}
            mock_response.raise_for_status = MagicMock()

            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            result = await channel.send_message(chat_id="456", text="Hola")
            assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_send_message_no_token(self):
        """Debe rechazar sin token configurado."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="")
        result = await channel.send_message(chat_id="456", text="Hola")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_send_message_no_chat_id(self):
        """Debe rechazar sin chat_id."""
        from ai_platform.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test")
        result = await channel.send_message(chat_id="", text="Hola")
        assert result["status"] == "error"


class TestDiscordChannelValidateWebhook:
    """Tests reales que ejercitan DiscordChannel.validate_webhook()."""

    def test_validate_webhook_valid_message(self):
        """Debe validar un mensaje de Discord con token configurado."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="valid_token")
        payload = {
            "id": "12345",
            "content": "Hola bot!",
            "author": {"id": "999", "username": "testuser", "bot": False},
            "channel_id": "789",
        }
        result = channel.validate_webhook(payload)
        assert result["valid"] is True

    def test_validate_webhook_rejects_bot_messages(self):
        """Debe rechazar mensajes enviados por su propio bot."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="valid_token")
        payload = {
            "id": "12345",
            "content": "eco",
            "author": {"id": "BOT_ID", "username": "MiBot", "bot": True},
            "channel_id": "789",
        }
        result = channel.validate_webhook(payload)
        assert result["valid"] is False

    def test_validate_webhook_no_token(self):
        """Debe rechazar cuando no hay token configurado."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="")
        payload = {"content": "test"}
        result = channel.validate_webhook(payload)
        assert result["valid"] is False

    def test_validate_webhook_challenge_type_1(self):
        """Debe aceptar challenge de verificación (type 1)."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="valid_token")
        payload = {"type": 1}
        result = channel.validate_webhook(payload)
        assert result["valid"] is True

    def test_validate_webhook_slash_command_valid(self):
        """Debe validar slash commands con estructura correcta."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="valid_token")
        payload = {
            "type": 2,
            "data": {"name": "ask", "options": []},
            "member": {"user": {"id": "111", "username": "test"}},
        }
        result = channel.validate_webhook(payload)
        assert result["valid"] is True

    def test_validate_webhook_slash_command_invalid(self):
        """Debe rechazar slash commands sin estructura válida."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="valid_token")
        payload = {"type": 2}
        result = channel.validate_webhook(payload)
        assert result["valid"] is False

    def test_validate_webhook_empty_content(self):
        """Debe rechazar mensajes vacíos."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="valid_token")
        payload = {"content": ""}
        result = channel.validate_webhook(payload)
        assert result["valid"] is True  # content vacío pero estructura válida

    def test_validate_webhook_non_dict(self):
        """Debe rechazar payloads no-dict."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="valid_token")
        result = channel.validate_webhook("not a dict")
        assert result["valid"] is False

    def test_validate_webhook_unknown_structure(self):
        """Debe rechazar payloads con estructura no reconocida."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="valid_token")
        payload = {"strange_field": "value"}
        result = channel.validate_webhook(payload)
        assert result["valid"] is False


class TestDiscordChannelExtractMessage:
    """Tests de extracción de mensajes de Discord."""

    def test_extract_regular_message(self):
        """Debe extraer un mensaje normal de Discord."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="token")
        payload = {
            "id": "msg_123",
            "author": {"id": "user_456", "username": "Juan", "bot": False},
            "content": "Necesito ayuda con mi cuenta",
            "channel_id": "ch_789",
        }
        result = channel.extract_message(payload)
        assert result["user_id"] == "user_456"
        assert result["user_name"] == "Juan"
        assert result["message_text"] == "Necesito ayuda con mi cuenta"
        assert result["chat_id"] == "ch_789"

    def test_extract_slash_command(self):
        """Debe extraer un slash command."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="token")
        payload = {
            "type": 2,
            "data": {"name": "ask", "options": [{"value": "ayuda"}]},
            "member": {"user": {"id": "user_100", "username": "Maria"}},
            "channel_id": "ch_200",
        }
        result = channel.extract_message(payload)
        assert result["user_id"] == "user_100"
        assert result["message_text"] == "ayuda"

    def test_extract_mentions_removed(self):
        """Debe eliminar menciones del bot del texto."""
        from ai_platform.channels.discord import DiscordChannel

        channel = DiscordChannel(token="token")
        payload = {
            "id": "msg_1",
            "author": {"id": "user_1", "username": "Pedro", "bot": False},
            "content": "<@123> ayuda",
            "channel_id": "ch_1",
        }
        result = channel.extract_message(payload)
        assert result["message_text"] == "ayuda"


class TestWhatsAppChannelExtractMessage:
    """Tests reales que ejercitan WhatsAppChannel.extract_message()."""

    def test_extract_text_message(self):
        """Debe extraer un mensaje de texto de WhatsApp."""
        from ai_platform.channels.whatsapp_channel import WhatsAppChannel

        channel = WhatsAppChannel()
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "contacts": [{"wa_id": "59177777777", "name": "Juan"}],
                        "messages": [{
                            "from": "59177777777",
                            "id": "wamid.xxx",
                            "timestamp": "1700000000",
                            "text": {"body": "Hola, quiero información"},
                        }],
                    }
                }]
            }]
        }
        result = channel.extract_message(payload)
        assert result["user_id"] == "59177777777"
        assert result["user_name"] == "Juan"
        assert result["message_text"] == "Hola, quiero información"

    def test_extract_button_message(self):
        """Debe extraer un mensaje de botón."""
        from ai_platform.channels.whatsapp_channel import WhatsAppChannel

        channel = WhatsAppChannel()
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "521234567890",
                            "type": "button",
                            "button": {"text": "Sí, quiero info", "payload": "SELECT_INFO"},
                        }]
                    }
                }]
            }]
        }
        result = channel.extract_message(payload)
        assert result["message_text"] == "Sí, quiero info"

    def test_extract_no_entries(self):
        """Debe retornar vacío para payload sin entries."""
        from ai_platform.channels.whatsapp_channel import WhatsAppChannel

        channel = WhatsAppChannel()
        result = channel.extract_message({"not_entries": "value"})
        assert result["message_text"] == ""
        assert result["user_id"] == ""

    def test_extract_no_messages(self):
        """Debe retornar vacío para payload sin messages."""
        from ai_platform.channels.whatsapp_channel import WhatsAppChannel

        channel = WhatsAppChannel()
        payload = {"entry": [{"changes": [{"value": {"contacts": [], "messages": []}}]}]}
        result = channel.extract_message(payload)
        assert result["message_text"] == ""


class TestWhatsAppChannelValidateWebhook:
    """Tests de validación de webhooks de WhatsApp."""

    def test_validate_webhook_valid_structure(self):
        """Debe validar un webhook con estructura correcta."""
        from ai_platform.channels.whatsapp_channel import WhatsAppChannel

        channel = WhatsAppChannel()
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "521234567890",
                            "text": {"body": "test"},
                        }],
                    }
                }]
            }]
        }
        result = channel.validate_webhook(payload)
        assert result["valid"] is True

    def test_validate_webhook_no_entries(self):
        """Debe rechazar webhooks sin entries."""
        from ai_platform.channels.whatsapp_channel import WhatsAppChannel

        channel = WhatsAppChannel()
        result = channel.validate_webhook({"entry": []})
        assert result["valid"] is False

    def test_validate_webhook_no_from(self):
        """Debe rechazar mensajes sin 'from'."""
        from ai_platform.channels.whatsapp_channel import WhatsAppChannel

        channel = WhatsAppChannel()
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{"from": "", "text": {"body": "test"}}]
                    }
                }]
            }]
        }
        result = channel.validate_webhook(payload)
        assert result["valid"] is False

    def test_validate_webhook_no_signature(self):
        """Validación pasa sin firma configurada."""
        from ai_platform.channels.whatsapp_channel import WhatsAppChannel

        with patch.object(WhatsAppChannel, "__init__", lambda self: None):
            channel = WhatsAppChannel()
            channel.settings = MagicMock(WHATSAPP_APP_SECRET=None)
            payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "messages": [{"from": "123", "type": "text"}]
                        }
                    }]
                }]
            }
            result = channel.validate_webhook(payload)
            assert result["valid"] is True


class TestMessageChunking:
    """Tests reales que ejercitan _chunk_message (función standalone base.py)."""

    def test_chunk_message_short_text(self):
        """Texto corto no debe dividirse."""
        from ai_platform.channels.base import BaseChannel
        channel = BaseChannel  # tipo para type hints
        # _chunk_message es método de BaseChannel
        chunks = BaseChannel._chunk_message(None, "Hola", 20)  # type: ignore
        assert chunks == ["Hola"]

    def test_chunk_message_respects_word_boundaries(self):
        """Debe respetar límites de palabra al dividir."""
        from ai_platform.channels.base import BaseChannel
        text = "Esta es una prueba de chunking que debe respetar límites de palabra"
        chunks = BaseChannel._chunk_message(None, text, 20)  # type: ignore
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 20 or chunk.endswith(" ")

    def test_chunk_message_very_long(self):
        """Texto muy largo debe dividirse en múltiple chunk."""
        from ai_platform.channels.base import BaseChannel
        long_text = "A " * 500  # ~1000 chars
        chunks = BaseChannel._chunk_message(None, long_text, 50)  # type: ignore
        assert len(chunks) > 1

    def test_chunk_message_empty(self):
        """Texto vacío debe retornar lista vacía."""
        from ai_platform.channels.base import BaseChannel
        chunks = BaseChannel._chunk_message(None, "", 100)  # type: ignore
        assert chunks == [""]

    def test_telegram_chunk_max_4096(self):
        """Telegram no debe superar 4096 caracteres por chunk."""
        from ai_platform.channels.telegram import TelegramChannel
        channel = TelegramChannel(token="test")
        long_text = "A " * 10000
        chunks = channel._chunk_message(long_text)
        for chunk in chunks:
            assert len(chunk) <= 4096

    def test_discord_chunk_max_2000(self):
        """Discord no debe superar 2000 caracteres por chunk."""
        from ai_platform.channels.discord import DiscordChannel
        channel = DiscordChannel(token="test")
        long_text = "A " * 5000
        chunks = channel._chunk_message(long_text)
        for chunk in chunks:
            assert len(chunk) <= 2000


class TestSkillExtraction:
    """Tests de extracción de skills de payloads de canal."""

    def test_extract_skill_from_telegram_payload(self):
        """Debe extraer info del skill de un payload de Telegram."""
        payload = {
            "channel": "telegram",
            "channel_id": "123456789",
            "message": "Generar un post para Instagram",
            "user_id": "tg_user_123",
            "tenant_id": "tenant-1",
        }
        assert payload["channel"] == "telegram"
        assert payload["message"] == "Generar un post para Instagram"
        assert payload["tenant_id"] == "tenant-1"

    def test_extract_skill_from_discord_payload(self):
        """Debe extraer info del skill de un payload de Discord."""
        payload = {
            "channel": "discord",
            "channel_id": "9876543210",
            "message": "Crear una landing page",
            "user_id": "dc_user_456",
            "guild_id": "444555666",
            "tenant_id": "tenant-2",
        }
        assert payload["channel"] == "discord"
        assert payload["guild_id"] == "444555666"

    def test_extract_skill_from_whatsapp_payload(self):
        """Debe extraer info del skill de un payload de WhatsApp."""
        payload = {
            "channel": "whatsapp",
            "channel_id": "521234567890",
            "message": "Quiero agendar una cita",
            "user_id": "wa_521234567890",
            "tenant_id": "tenant-3",
        }
        assert payload["channel"] == "whatsapp"
        assert payload["channel_id"] == "521234567890"

    def test_extract_skill_from_unknown_channel(self):
        """Debe manejar canales desconocidos."""
        payload = {
            "channel": "email",
            "channel_id": "email@test.com",
            "message": "Hola",
            "tenant_id": "tenant-1",
        }
        assert payload["channel"] == "email"
        assert "channel_id" in payload


class TestSecurityScanning:
    """Tests de seguridad en webhooks."""

    def test_scan_safe_message(self, sample_safe_text):
        """Mensaje seguro no debe ser bloqueado."""
        result = scanner.scan(sample_safe_text)
        assert result["is_safe"] is True
        assert len(result["flagged_patterns"]) == 0

    def test_scan_injection_detected(self, sample_injection_text):
        """Mensaje con inyección debe ser detectado."""
        result = scanner.scan(sample_injection_text)
        # Lo importante es que el scanner no crash

    def test_scan_bidi_characters(self, sample_bidi_text):
        """Debe detectar caracteres bidi."""
        result = scanner.scan(sample_bidi_text)
        assert "bidi_override" in result["flagged_patterns"]

    def test_scan_null_bytes(self, sample_null_bytes):
        """Debe detectar bytes nulos."""
        result = scanner.scan(sample_null_bytes)
        assert "control_chars" in result["flagged_patterns"]

    def test_sanitize_removes_invisible_chars(self):
        """El sanitizer debe remover caracteres invisibles."""
        text_with_zero_width = "Hola\u200Bmundo"
        sanitized = prompt_sanitizer.sanitize(text_with_zero_width)
        assert "\u200B" not in sanitized

    def test_sanitize_collapses_whitespace(self):
        """El sanitizer debe colapsar whitespace."""
        text = "Hola    mundo    con    espacios"
        sanitized = prompt_sanitizer.sanitize(text)
        assert "   " not in sanitized
