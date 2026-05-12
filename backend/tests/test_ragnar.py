"""
Tests para el orquestador Ragnar.

Prueba:
- decide() con diferentes prompts
- Routing a módulos correctos
- Gestión de sesiones
- Manejo de errores
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_platform.orchestrator.ragnar import Ragnar, get_ragnar
from ai_platform.orchestrator.llm_client import ROUTING_MODELS


class TestRagnarDecide:
    """Tests del método decide()."""

    @pytest.fixture
    def ragnar(self):
        """Crear instancia de Ragnar con mocks."""
        with patch("ai_platform.orchestrator.ragnar.LLMClient") as mock_llm_cls, \
             patch("ai_platform.orchestrator.ragnar.SessionManager") as mock_sm_cls, \
             patch("ai_platform.orchestrator.ragnar.MemoryManager") as mock_mm_cls, \
             patch("ai_platform.orchestrator.ragnar.SkillManager") as mock_skill_cls, \
             patch("ai_platform.orchestrator.ragnar.BudgetTracker") as mock_budget_cls, \
             patch("ai_platform.orchestrator.ragnar.DecisionLogger") as mock_dl_cls:

            mock_llm = MagicMock()
            mock_llm.route_task = AsyncMock()
            mock_llm._route_with_fallback = AsyncMock()
            mock_llm.decompose_task = AsyncMock()
            mock_llm.extract_params = AsyncMock()

            mock_sm = MagicMock()
            mock_sm.get_or_create = AsyncMock()
            mock_sm.get_context = AsyncMock()
            mock_sm.close = AsyncMock()

            mock_mm = MagicMock()
            mock_mm.prefetch = AsyncMock()
            mock_mm.sync_turn = AsyncMock()
            mock_mm.close = AsyncMock()

            mock_skill = MagicMock()
            mock_skill.close = AsyncMock()

            mock_budget = MagicMock()
            mock_budget.begin_task = AsyncMock()
            mock_budget.end_task = AsyncMock()
            mock_budget.close = AsyncMock()

            mock_dl = MagicMock()

            mock_llm_cls.return_value = mock_llm
            mock_sm_cls.return_value = mock_sm
            mock_mm_cls.return_value = mock_mm
            mock_skill_cls.return_value = mock_skill
            mock_budget_cls.return_value = mock_budget
            mock_dl_cls.return_value = mock_dl

            return Ragnar()

    async def test_decide_requires_tenant_id(self, ragnar):
        """decide() debe requerir tenant_id."""
        with pytest.raises(ValueError, match="tenant_id es obligatorio"):
            await ragnar.decide(
                prompt="Hola",
                tenant_id=None,
            )

    async def test_decide_routes_ai_connect(self, ragnar):
        """decide() debe enrutar prompts de mensajería a ai-connect."""
        ragnar.llm_client.route_task = AsyncMock(return_value={
            "module": "ai-connect",
            "action": "send_whatsapp",
            "confidence": 0.9,
            "reasoning": "El usuario quiere enviar un mensaje",
            "needs_decomposition": False,
        })
        ragnar.session_manager.get_or_create = AsyncMock(return_value={
            "id": "session-123",
            "tenant_id": "tenant-1",
        })
        ragnar.session_manager.get_context = AsyncMock(return_value={
            "recent_messages": [],
            "session_info": {},
        })

        result = await ragnar.decide(
            prompt="Enviar un mensaje de WhatsApp a +51999999999",
            tenant_id="tenant-1",
        )

        assert result["module"] == "ai-connect"
        assert result["action"] == "send_whatsapp"
        assert result["confidence"] == 0.9
        assert result["session_id"] == "session-123"

    async def test_decide_routes_ai_social(self, ragnar):
        """decide() debe enrutar prompts de redes sociales a ai-social."""
        ragnar.llm_client.route_task = AsyncMock(return_value={
            "module": "ai-social",
            "action": "create_post",
            "confidence": 0.85,
            "reasoning": "El usuario quiere publicar en redes sociales",
            "needs_decomposition": False,
        })
        ragnar.session_manager.get_or_create = AsyncMock(return_value={
            "id": "session-456",
            "tenant_id": "tenant-1",
        })
        ragnar.session_manager.get_context = AsyncMock(return_value={
            "recent_messages": [],
            "session_info": {},
        })

        result = await ragnar.decide(
            prompt="Crear un post para Instagram sobre nuestro producto",
            tenant_id="tenant-1",
        )

        assert result["module"] == "ai-social"
        assert result["action"] == "create_post"

    async def test_decide_routes_ai_web(self, ragnar):
        """decide() debe enrutar prompts de web a ai-web."""
        ragnar.llm_client.route_task = AsyncMock(return_value={
            "module": "ai-web",
            "action": "generate_page",
            "confidence": 0.95,
            "reasoning": "El usuario quiere generar una página web",
            "needs_decomposition": False,
        })
        ragnar.session_manager.get_or_create = AsyncMock(return_value={
            "id": "session-789",
            "tenant_id": "tenant-1",
        })
        ragnar.session_manager.get_context = AsyncMock(return_value={
            "recent_messages": [],
            "session_info": {},
        })

        result = await ragnar.decide(
            prompt="Crear una landing page para mi negocio",
            tenant_id="tenant-1",
        )

        assert result["module"] == "ai-web"
        assert result["action"] == "generate_page"

    async def test_decide_handles_uncategorized(self, ragnar):
        """decide() debe manejar prompts no categorizados."""
        ragnar.llm_client.route_task = AsyncMock(return_value={
            "module": "uncategorized",
            "action": "unknown",
            "confidence": 0.0,
            "reasoning": "No se pudo determinar el módulo",
            "needs_decomposition": False,
        })
        ragnar.session_manager.get_or_create = AsyncMock(return_value={
            "id": "session-uncat",
            "tenant_id": "tenant-1",
        })
        ragnar.session_manager.get_context = AsyncMock(return_value={
            "recent_messages": [],
            "session_info": {},
        })

        result = await ragnar.decide(
            prompt="algo que no encaja en ningún módulo",
            tenant_id="tenant-1",
        )

        assert result["module"] == "uncategorized"
        assert result["confidence"] == 0.0

    async def test_decide_handles_llm_failure(self, ragnar):
        """decide() debe manejar fallos del LLM con fallback."""
        ragnar.llm_client.route_task = AsyncMock(side_effect=RuntimeError("API key no configurada"))
        ragnar.llm_client._route_with_fallback = AsyncMock(return_value={
            "module": "ai-connect",
            "action": "send_message",
            "params": {},
            "confidence": 0.7,
            "reasoning": "Rule-based: detected messaging keywords",
            "needs_decomposition": False,
        })
        ragnar.session_manager.get_or_create = AsyncMock(return_value={
            "id": "session-fallback",
            "tenant_id": "tenant-1",
        })
        ragnar.session_manager.get_context = AsyncMock(return_value={
            "recent_messages": [],
            "session_info": {},
        })

        result = await ragnar.decide(
            prompt="Enviar mensaje de WhatsApp",
            tenant_id="tenant-1",
        )

        assert result["module"] == "ai-connect"
        assert result["confidence"] == 0.7

    async def test_decide_returns_session_id(self, ragnar):
        """decide() debe retornar session_id."""
        ragnar.llm_client.route_task = AsyncMock(return_value={
            "module": "ai-content",
            "action": "generate",
            "confidence": 0.8,
            "reasoning": "Generar contenido",
            "needs_decomposition": False,
        })
        ragnar.session_manager.get_or_create = AsyncMock(return_value={
            "id": "session-returned",
            "tenant_id": "tenant-1",
        })
        ragnar.session_manager.get_context = AsyncMock(return_value={
            "recent_messages": [],
            "session_info": {},
        })

        result = await ragnar.decide(
            prompt="Generar un blog post sobre marketing",
            tenant_id="tenant-1",
        )

        assert "session_id" in result
        assert result["session_id"] == "session-returned"

    async def test_decide_with_existing_session(self, ragnar):
        """decide() debe reutilizar sesión existente."""
        ragnar.llm_client.route_task = AsyncMock(return_value={
            "module": "ai-content",
            "action": "generate",
            "confidence": 0.8,
            "reasoning": "Generar contenido",
            "needs_decomposition": False,
        })
        ragnar.session_manager.get_or_create = AsyncMock(return_value={
            "id": "existing-session",
            "tenant_id": "tenant-1",
        })
        ragnar.session_manager.get_context = AsyncMock(return_value={
            "recent_messages": [{"role": "user", "content": "Hola"}],
            "session_info": {"id": "existing-session"},
        })

        result = await ragnar.decide(
            prompt="Continuar con el blog post",
            tenant_id="tenant-1",
            session_id="existing-session",
        )

        assert result["session_id"] == "existing-session"
        assert len(result.get("session_context", {}).get("recent_messages", [])) > 0


class TestRagnarExecute:
    """Tests del método execute()."""

    @pytest.fixture
    def ragnar(self):
        """Crear instancia de Ragnar con mocks."""
        with patch("ai_platform.orchestrator.ragnar.LLMClient") as mock_llm_cls, \
             patch("ai_platform.orchestrator.ragnar.SessionManager") as mock_sm_cls, \
             patch("ai_platform.orchestrator.ragnar.MemoryManager") as mock_mm_cls, \
             patch("ai_platform.orchestrator.ragnar.SkillManager") as mock_skill_cls, \
             patch("ai_platform.orchestrator.ragnar.BudgetTracker") as mock_budget_cls, \
             patch("ai_platform.orchestrator.ragnar.DecisionLogger") as mock_dl_cls:

            mock_llm = MagicMock()
            mock_llm.route_task = AsyncMock()
            mock_llm._route_with_fallback = AsyncMock()
            mock_llm.decompose_task = AsyncMock()
            mock_llm.extract_params = AsyncMock()

            mock_sm = MagicMock()
            mock_sm.get_or_create = AsyncMock()
            mock_sm.get_context = AsyncMock()
            mock_sm.close = AsyncMock()

            mock_mm = MagicMock()
            mock_mm.prefetch = AsyncMock()
            mock_mm.sync_turn = AsyncMock()
            mock_mm.close = AsyncMock()

            mock_skill = MagicMock()
            mock_skill.close = AsyncMock()

            mock_budget = MagicMock()
            mock_budget.begin_task = AsyncMock()
            mock_budget.end_task = AsyncMock()
            mock_budget.close = AsyncMock()

            mock_dl = MagicMock()

            mock_llm_cls.return_value = mock_llm
            mock_sm_cls.return_value = mock_sm
            mock_mm_cls.return_value = mock_mm
            mock_skill_cls.return_value = mock_skill
            mock_budget_cls.return_value = mock_budget
            mock_dl_cls.return_value = mock_dl

            return Ragnar()

    async def test_execute_uncategorized_fails(self, ragnar):
        """execute() debe fallar para módulo uncategorized."""
        decision = {
            "module": "uncategorized",
            "params": {},
        }

        result = await ragnar.execute(
            decision=decision,
            tenant_id="tenant-1",
            task_id="task-1",
        )

        assert result["status"] == "failed"
        assert "error" in result["result"]

    async def test_execute_unsupported_module(self, ragnar):
        """execute() debe manejar módulos no soportados."""
        decision = {
            "module": "ai-unknown",
            "params": {},
        }

        result = await ragnar.execute(
            decision=decision,
            tenant_id="tenant-1",
            task_id="task-2",
        )

        assert result["status"] == "error"
        assert "no soportado" in result["error"]

    async def test_execute_enriches_payload(self, ragnar):
        """execute() debe enriquecer la payload con contexto."""
        ragnar.budget_tracker.begin_task = AsyncMock()
        ragnar.budget_tracker.end_task = AsyncMock()
        ragnar.memory_manager.sync_turn = AsyncMock()

        # Mock del _invoke_module para interceptar la payload
        original_invoke = ragnar._invoke_module
        captured_payload = {}

        async def mock_invoke(module, payload):
            nonlocal captured_payload
            captured_payload = payload
            return {"status": "ok"}

        ragnar._invoke_module = mock_invoke

        decision = {
            "module": "ai-connect",
            "params": {"action": "test"},
            "session_context": {"tenant_id": "tenant-1"},
            "memory_context": {"memory": "test memory"},
        }

        await ragnar.execute(
            decision=decision,
            tenant_id="tenant-1",
            task_id="task-3",
        )

        assert "tenant_id" in captured_payload
        assert "session_context" in captured_payload
        assert "memory_context" in captured_payload


class TestRagnarSingleton:
    """Tests del patrón singleton."""

    def test_get_ragnar_returns_instance(self):
        """get_ragnar() debe retornar una instancia de Ragnar."""
        with patch("ai_platform.orchestrator.ragnar.LLMClient"), \
             patch("ai_platform.orchestrator.ragnar.SessionManager"), \
             patch("ai_platform.orchestrator.ragnar.MemoryManager"), \
             patch("ai_platform.orchestrator.ragnar.SkillManager"), \
             patch("ai_platform.orchestrator.ragnar.BudgetTracker"), \
             patch("ai_platform.orchestrator.ragnar.DecisionLogger"):

            ragnar = get_ragnar()
            assert ragnar is not None
            assert isinstance(ragnar, Ragnar)
