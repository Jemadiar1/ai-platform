"""
Tests para los handlers de módulos.

Prueba:
- ai-connect handler con varias acciones
- ai-content handler
- ai-social handler
- Otros módulos (ai-leads, ai-ads, etc.)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from datetime import datetime

from ai_platform.modules.ai_connect.handler import Handler as ConnectHandler
from ai_platform.modules.ai_content.handler import Handler as ContentHandler
from ai_platform.modules.ai_social.handler import Handler as SocialHandler
from ai_platform.modules.ai_leads.handler import Handler as LeadsHandler
from ai_platform.modules.ai_ads.handler import Handler as AdsHandler
from ai_platform.modules.ai_analytics.handler import Handler as AnalyticsHandler
from ai_platform.modules.ai_web.handler import Handler as WebHandler


class TestAiConnectHandler:
    """Tests del handler ai-connect."""

    @pytest.fixture
    def handler(self):
        return ConnectHandler()

    def test_execute_send_whatsapp(self, handler):
        """Debe ejecutar acción de enviar WhatsApp."""
        payload = {
            "action": "send_whatsapp_message",
            "to": "+51999999999",
            "message": "Hola, esto es una prueba",
        }

        result = handler.execute(payload)

        assert result["action"] == "send_whatsapp_message"
        assert result["status"] == "success"
        assert "message_id" in result["result"]
        assert result["result"]["to"] == "+51999999999"

    def test_execute_send_whatsapp_invalid_phone(self, handler):
        """Debe rechazar número de teléfono inválido."""
        payload = {
            "action": "send_whatsapp_message",
            "to": "12345",
            "message": "Hola",
        }

        with pytest.raises(ValueError, match="formato E.164"):
            handler.execute(payload)

    def test_execute_send_whatsapp_no_phone(self, handler):
        """Debe rechalar acción sin número de teléfono."""
        payload = {
            "action": "send_whatsapp_message",
            "message": "Hola",
        }

        with pytest.raises(ValueError, match="Se requieren"):
            handler.execute(payload)

    def test_execute_voice_call(self, handler):
        """Debe ejecutar acción de llamada de voz."""
        payload = {
            "action": "make_voice_call",
            "phone_number": "+51999999999",
            "agent_id": "agent_123",
        }

        result = handler.execute(payload)

        assert result["action"] == "make_voice_call"
        assert result["status"] == "success"
        assert "call_id" in result["result"]

    def test_execute_voice_call_invalid_phone(self, handler):
        """Debe rechazar número inválido para llamada de voz."""
        payload = {
            "action": "make_voice_call",
            "phone_number": "12345",
        }

        with pytest.raises(ValueError, match="formato E.164"):
            handler.execute(payload)

    def test_execute_handle_chat(self, handler):
        """Debe manejar mensaje de chat en vivo."""
        payload = {
            "action": "handle_chat_message",
            "message": "Hola, quiero información",
        }

        result = handler.execute(payload)

        assert result["action"] == "handle_chat_message"
        assert result["status"] == "handled"
        assert "response" in result["result"]

    def test_execute_schedule_appointment(self, handler):
        """Debe programar una cita."""
        payload = {
            "action": "schedule_appointment",
            "date": "2026-06-15",
            "time": "10:00",
            "title": "Consulta",
        }

        result = handler.execute(payload)

        assert result["action"] == "schedule_appointment"
        assert result["status"] == "success"
        assert result["result"]["date"] == "2026-06-15"

    def test_execute_update_contact(self, handler):
        """Debe actualizar contacto."""
        payload = {
            "action": "update_contact",
            "name": "Juan Pérez",
            "email": "juan@email.com",
            "phone": "+51999999999",
        }

        result = handler.execute(payload)

        assert result["action"] == "update_contact"
        assert result["status"] == "success"
        assert result["result"]["name"] == "Juan Pérez"

    def test_execute_get_contacts(self, handler):
        """Debe listar contactos."""
        payload = {
            "action": "get_contacts",
            "search": "juan",
            "limit": 50,
        }

        result = handler.execute(payload)

        assert result["action"] == "get_contacts"
        assert "contacts" in result["result"]
        assert "total" in result["result"]

    def test_execute_invalid_action(self, handler):
        """Debe rechazar acción inválida."""
        payload = {
            "action": "invalid_action",
        }

        with pytest.raises(ValueError, match="Acción no soportada"):
            handler.execute(payload)

    def test_execute_no_action(self, handler):
        """Debe rechazar payload sin acción."""
        payload = {}

        with pytest.raises(ValueError, match="No se especificó una acción"):
            handler.execute(payload)


class TestAiContentHandler:
    """Tests del handler ai-content."""

    @pytest.fixture
    def handler(self):
        return ContentHandler()

    def test_execute_default_action(self, handler):
        """Debe ejecutar acción por defecto."""
        payload = {
            "action": "generate_post",
            "topic": "marketing digital",
        }

        result = handler.execute(payload)

        assert result["action"] == "generate_post"
        assert result["status"] == "success"
        assert "note" in result

    def test_execute_empty_payload(self, handler):
        """Debe manejar payload vacío."""
        result = handler.execute({})

        assert result["action"] == "default"
        assert result["status"] == "success"


class TestAiSocialHandler:
    """Tests del handler ai-social."""

    @pytest.fixture
    def handler(self):
        return SocialHandler()

    def test_execute_create_post(self, handler):
        """Debe crear un post para redes sociales."""
        payload = {
            "action": "create_post",
            "platform": "instagram",
            "content": "Nuevo producto disponible",
        }

        result = handler.execute(payload)

        assert result["action"] == "create_post"
        assert result["status"] == "success"

    def test_execute_analyze_engagement(self, handler):
        """Debe analizar engagement de redes sociales."""
        payload = {
            "action": "analyze_engagement",
            "platform": "facebook",
            "post_id": "post_123",
        }

        result = handler.execute(payload)

        assert result["action"] == "analyze_engagement"
        assert result["status"] == "success"


class TestAiLeadsHandler:
    """Tests del handler ai-leads."""

    @pytest.fixture
    def handler(self):
        return LeadsHandler()

    def test_execute_generate_leads(self, handler):
        """Debe generar leads."""
        payload = {
            "action": "generate_leads",
            "industry": "tecnología",
            "target_audience": "dueños de negocio",
        }

        result = handler.execute(payload)

        assert result["action"] == "generate_leads"
        assert result["status"] == "success"


class TestAiAdsHandler:
    """Tests del handler ai-ads."""

    @pytest.fixture
    def handler(self):
        return AdsHandler()

    def test_execute_create_campaign(self, handler):
        """Debe crear una campaña publicitaria."""
        payload = {
            "action": "create_campaign",
            "platform": "meta",
            "budget": 500,
            "duration_days": 30,
        }

        result = handler.execute(payload)

        assert result["action"] == "create_campaign"
        assert result["status"] == "success"


class TestAiAnalyticsHandler:
    """Tests del handler ai-analytics."""

    @pytest.fixture
    def handler(self):
        return AnalyticsHandler()

    def test_execute_generate_report(self, handler):
        """Debe generar un reporte de analytics."""
        payload = {
            "action": "generate_report",
            "report_type": "monthly",
            "date_range": "2026-01-01:2026-01-31",
        }

        result = handler.execute(payload)

        assert result["action"] == "generate_report"
        assert result["status"] == "success"


class TestAiWebHandler:
    """Tests del handler ai-web."""

    @pytest.fixture
    def handler(self):
        return WebHandler()

    def test_execute_generate_page(self, handler):
        """Debe generar una página web."""
        payload = {
            "action": "generate_page",
            "page_type": "landing",
            "topic": "servicios de marketing",
        }

        result = handler.execute(payload)

        assert result["action"] == "generate_page"
        assert result["status"] == "success"
