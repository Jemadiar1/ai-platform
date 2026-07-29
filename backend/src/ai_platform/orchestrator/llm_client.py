"""
Cliente NAN para decisiones de orquestación.

Odin usa un LLM para decidir:
- Qué módulo ejecutar dado un input del usuario
- Qué parámetros extraer del input
- Cuánto contexto proporcionar a cada módulo

Modelos usados:
- qwen3.6: Modelo principal para routing, planning y descomposición

Patrones de optimización:
- Prompt caching para Claude (reduce costos 75%)
- Fallback routing si un modelo falla
- Timeout de 30 segundos por decisión
"""

import asyncio
import base64
import json
import logging
from typing import Any

import httpx

from ai_platform.core.config import get_settings
from ai_platform.orchestrator.pricing import calculate_cost
from ai_platform.orchestrator.rate_limiter import get_rate_limit_tracker

logger = logging.getLogger(__name__)
settings = get_settings()

# Modelos disponibles para decisiones de orquestación
ROUTING_MODELS = {
    "primary": "qwen3.6",
    "fallback": "qwen3.6",
    "fast": "qwen3.6",
}

# Timeout de 12 segundos por llamada LLM para fallbacks interactivos veloces
LLM_TIMEOUT = 12.0

# Headers para prompt caching de Claude
ANTHROPIC_CACHE_HEADER = {"anthropic-beta": "prompt-caching-2024-07-31"}

# Marcador de punto de cacheo para Claude
CACHE_BREAKPOINT = "\n--- INICIO DEL PROMPT DEL SISTEMA (este contenido se cachea) ---"


class LLMClient:
    """
    Cliente NAN para decisiones de orquestación.

    Encapsula las llamadas a LLM que Odin usa para:
    - Clasificar y enrutar tareas
    - Descomponer tareas complejas en subtasks
    - Extraer parámetros de los inputs de usuario
    - Tomar decisiones de coordinación entre módulos
    """

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.NAN_API_URL
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.settings.NAN_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Jemadiar1/ai-platform",
                "X-Title": "AI Platform - NeuralCrew Labs",
            },
            timeout=LLM_TIMEOUT,
        )
        self._chat_path = "/chat/completions"
        self._rate_tracker = get_rate_limit_tracker()

    # =========================================================================
    # Routing principal
    # =========================================================================

    async def route_task(
        self,
        prompt: str,
        tenant_id: str,
        history: list[dict] | None = None,
        memory_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Decidir qué módulo debe ejecutar una tarea."""
        if not self.settings.NAN_API_KEY:
            logger.warning("NAN_API_KEY no configurada. Usando fallback de routing inmediato.")
            return await self._route_with_fallback(prompt, tenant_id, history)

        user_profile = ""
        if memory_context:
            user_profile = memory_context.get("cross_session_user", "")

        system_prompt = self._build_routing_system_prompt(tenant_id, history, user_profile=user_profile)
        user_message = self._build_routing_user_prompt(prompt, history)

        model = self.settings.PRIMARY_MODEL or ROUTING_MODELS["primary"]
        is_claude = "claude" in model

        self._rate_tracker.wait_if_needed("nan")

        try:
            response = await self.client.post(
                self._chat_path,
                json={
                    "model": model,
                    "messages": self._build_cached_messages(
                        system_prompt=system_prompt,
                        user_message=user_message,
                        use_cache=is_claude and self.settings.USE_PROMPT_CACHE,
                    ),
                    "max_tokens": 1024,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    **({"extra_headers": ANTHROPIC_CACHE_HEADER} if is_claude else {}),
                },
            )

            self._rate_tracker.record_request("nan", success=response.status_code == 200)

            if response.status_code == 200:
                data = response.json()
                result = self._parse_routing_response(data)
                self._record_llm_cost(model, data, result)
                return result

            logger.warning(f"Routing LLM failed with status {response.status_code}. Attempting fallback.")
            return await self._route_with_fallback(prompt, tenant_id, history)

        except httpx.TimeoutException:
            logger.warning("Routing LLM timed out. Using fallback.")
            self._rate_tracker.record_request("nan", success=False)
            return await self._route_with_fallback(prompt, tenant_id, history)
        except Exception as e:
            logger.error(f"Routing LLM error: {e}", exc_info=True)
            self._rate_tracker.record_request("nan", success=False)
            return await self._route_with_fallback(prompt, tenant_id, history)

    # =========================================================================
    # Descomposición de tareas
    # =========================================================================

    async def decompose_task(self, complex_prompt: str, tenant_id: str) -> list[dict[str, Any]]:
        """Descomponer una tarea compleja en subtasks."""
        if not self.settings.NAN_API_KEY:
            raise ValueError("NAN_API_KEY no está configurada.")

        system_prompt = self._build_decompose_system_prompt(tenant_id)
        user_message = f"Decompone la siguiente tarea en pasos específicos:\n\n{complex_prompt}"

        model = self.settings.PRIMARY_MODEL or ROUTING_MODELS["primary"]
        is_claude = "claude" in model

        self._rate_tracker.wait_if_needed("nan")

        try:
            response = await self.client.post(
                self._chat_path,
                json={
                    "model": model,
                    "messages": self._build_cached_messages(
                        system_prompt=system_prompt,
                        user_message=user_message,
                        use_cache=is_claude and self.settings.USE_PROMPT_CACHE,
                    ),
                    "max_tokens": 2048,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    **({"extra_headers": ANTHROPIC_CACHE_HEADER} if is_claude else {}),
                },
            )

            self._rate_tracker.record_request("nan", success=response.status_code == 200)

            if response.status_code == 200:
                data = response.json()
                result = self._parse_decompose_response(data)
                self._record_llm_cost(model, data, result)
                return result

            logger.warning("Decomposition LLM failed. Using fallback.")
            return await self._decompose_with_fallback(complex_prompt, tenant_id)

        except Exception as e:
            logger.error(f"Decomposition LLM error: {e}", exc_info=True)
            self._rate_tracker.record_request("nan", success=False)
            return await self._decompose_with_fallback(complex_prompt, tenant_id)

    # =========================================================================
    # Extracción de parámetros
    # =========================================================================

    async def extract_params(self, prompt: str, module: str, action: str) -> dict[str, Any]:
        """Extraer parámetros relevantes de un input para un módulo específico."""
        if not self.settings.NAN_API_KEY:
            raise ValueError("NAN_API_KEY no está configurada.")

        system_prompt = self._build_extract_system_prompt(module, action)
        user_message = f"Extrae los parámetros relevantes de este input:\n\n{prompt}"

        model = self.settings.FAST_MODEL or ROUTING_MODELS["fast"]
        is_claude = "claude" in model

        self._rate_tracker.wait_if_needed("nan")

        try:
            response = await self.client.post(
                self._chat_path,
                json={
                    "model": model,
                    "messages": self._build_cached_messages(
                        system_prompt=system_prompt,
                        user_message=user_message,
                        use_cache=is_claude and self.settings.USE_PROMPT_CACHE,
                    ),
                    "max_tokens": 512,
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                    **({"extra_headers": ANTHROPIC_CACHE_HEADER} if is_claude else {}),
                },
            )

            self._rate_tracker.record_request("nan", success=response.status_code == 200)

            if response.status_code == 200:
                data = response.json()
                result = self._parse_extract_params_response(data)
                return result

            logger.warning("Param extraction LLM failed. Using fallback.")
            return await self._extract_params_fallback(module, action, prompt)

        except Exception as e:
            logger.error(f"Param extraction LLM error: {e}", exc_info=True)
            self._rate_tracker.record_request("nan", success=False)
            return await self._extract_params_fallback(module, action, prompt)

    # =========================================================================
    # Chat simple (respuesta conversacional)
    # =========================================================================

    async def chat(self, prompt: str, tenant_id: str = "", user_id: str = "") -> dict[str, Any]:
        """Enviar un mensaje al LLM y obtener una respuesta conversacional."""
        model = self.settings.PRIMARY_MODEL or "qwen3.6"

        try:
            response = await self.client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "Eres un asistente de marketing digital profesional de NeuralCrew Labs.\n\n"
                                "Capacidades:\n"
                                "- Generar contenido: blogs, emails, posts para redes sociales, copy publicitario, SEO\n"
                                "- Crear páginas web con HTML/CSS responsivo\n"
                                "- Generar documentos: DOCX, XLSX, PPTX, PDF, PNG\n"
                                "- Crear campañas publicitarias para Meta, Google, TikTok, LinkedIn\n"
                                "- Generar leads calificados B2B/B2C\n"
                                "- Analizar engagement y métricas de redes sociales\n\n"
                                "Reglas:\n"
                                "- Responde siempre en español\n"
                                "- Sé profesional, útil y conciso\n"
                                "- Si el usuario pide un documento específico (PDF, DOCX, etc.), indícale que se procesará\n"
                                "- Si no estás seguro de qué módulo usar, sugiere el más apropiado\n"
                                "- No inventes datos ni hagas afirmaciones sin base\n\n"
                                f"Usuario: {prompt}"
                            ),
                        },
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.7,
                },
            )

            if response is None or response.status_code != 200:
                error_detail = response.text[:200] if response else "No response received"
                logger.warning(f"Chat LLM failed: {error_detail}")
                return {
                    "content": "Lo siento, estoy teniendo problemas para generar una respuesta. Intenta de nuevo.",
                    "model": model,
                }

            data = response.json()
            content = ""
            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                content = choice.get("message", {}).get("content") or ""

            if content and content.strip():
                _truncated = choice.get("finish_reason") == "length"
                result = {"content": content.strip(), "model": model, "_truncated": _truncated}
                if _truncated:
                    logger.warning(f"Response truncated. Prompt: {len(prompt)} chars")
                return result
        except Exception as e:
            logger.error(f"Chat LLM error: {e}", exc_info=True)
            return {
                "content": "Lo siento, estoy teniendo problemas para generar una respuesta. Intenta de nuevo.",
                "model": model,
            }

    # =========================================================================
    # Chat con visión (imágenes)
    # =========================================================================

    async def vision_chat(
        self,
        prompt: str,
        png_bytes: bytes,
        tenant_id: str = "",
        user_id: str = "",
    ) -> dict[str, Any]:
        """Enviar una imagen y un prompt al LLM con visión."""
        model = self.settings.VISION_MODEL or "gpt-4o"

        max_retries = 2
        for attempt in range(max_retries):
            try:
                b64 = base64.b64encode(png_bytes).decode("utf-8")
                content = [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64}",
                            "detail": "high",
                        },
                    },
                ]

                response = await self.client.post(
                    "/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": content}],
                        "max_tokens": 512,
                        "temperature": 0.5,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    text = ""
                    if "choices" in data and len(data["choices"]) > 0:
                        choice = data["choices"][0]
                        text = choice.get("message", {}).get("content", "")
                    return {"text": text.strip(), "model": model}

                logger.warning(f"vision_chat({model}) attempt {attempt+1}/{max_retries} failed: {response.status_code}")

                if attempt == 0 and self.settings.VISION_MODEL_SECONDARY:
                    model = self.settings.VISION_MODEL_SECONDARY
                    self.client = httpx.AsyncClient(
                        base_url=self.base_url,
                        headers={
                            "Authorization": f"Bearer {self.settings.NAN_API_KEY}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://github.com/Jemadiar1/ai-platform",
                            "X-Title": "AI Platform - NeuralCrew Labs",
                        },
                        timeout=LLM_TIMEOUT,
                    )
                    continue

            except Exception as e:
                logger.error(f"vision_chat attempt {attempt+1} error: {e}", exc_info=True)
                if attempt == 0 and self.settings.VISION_MODEL_SECONDARY:
                    model = self.settings.VISION_MODEL_SECONDARY
                    self.client = httpx.AsyncClient(
                        base_url=self.base_url,
                        headers={
                            "Authorization": f"Bearer {self.settings.NAN_API_KEY}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://github.com/Jemadiar1/ai-platform",
                            "X-Title": "AI Platform - NeuralCrew Labs",
                        },
                        timeout=LLM_TIMEOUT,
                    )
                    continue

        logger.error(f"vision_chat failed after {max_retries} attempts")
        return {
            "text": "Lo siento, no pude analizar la imagen. Intenta de nuevo.",
            "model": "error",
        }

    async def close(self):
        """Cerrar el cliente HTTP."""
        try:
            await self.client.aclose()
        except Exception:
            pass

    # =========================================================================
    # Métodos privados - Construcción de prompts
    # =========================================================================

    def _build_routing_system_prompt(
        self, tenant_id: str, history: list[dict] | None = None, user_profile: str = ""
    ) -> str:
        """Construir el prompt del sistema para routing."""
        from ai_platform.orchestrator.modules import get_route_modules_description

        module_desc = get_route_modules_description()

        system = f"""Eres Odin, el orquestador de NeuralCrew Labs, una agencia de marketing 100% potenciada por IA.
Tu trabajo es decidir qué módulo debe ejecutar una tarea basada en el input del usuario.

{module_desc}

Reglas de decisión:
1. Elige EXACTAMENTE UN módulo que mejor resuelva la solicitud del usuario.
2. Si la solicitud es ambigua, elige el módulo más genérico (ai-connect).
3. Para generación de documentos (Word, Excel, PowerPoint, PDF, imágenes), usa ai-documents.
4. Para mensajes conversacionales o preguntas generales, usa ai-connect.
5. Para contenido de redes sociales, usa ai-social.
6. Para análisis, reportes, OCR, investigación web, usa ai-analytics.
7. Para landing pages o páginas web, usa ai-web.
8. Para generar leads, usa ai-leads.
9. Para campañas publicitarias, usa ai-ads.
10. Para generar texto (posts, blogs, copy), usa ai-content.

Si la solicitud no encaja en ningún módulo específico, usa "uncategorized" y Odin manejará el fallback.

El output debe ser JSON con estas claves:
- module: nombre del módulo
- action: acción específica dentro del módulo
- params: parámetros extraídos del prompt
- confidence: score entre 0.0 y 1.0
- reasoning: explicación breve de la decisión
- needs_decomposition: true si la tarea es compleja y requiere múltiples pasos

"""

        if user_profile:
            system += f"\nPerfil del usuario: {user_profile}\n"

        system += CACHE_BREAKPOINT

        return system

    def _build_routing_user_prompt(self, prompt: str, history: list[dict] | None = None) -> str:
        """Construir el prompt del usuario para routing."""
        user_input = f"Input del usuario: {prompt}"

        if history and len(history) > 0:
            recent = history[-3:]  # Últimos 3 mensajes como contexto
            ctx_lines = []
            for msg in recent:
                role = msg.get("role", "user")
                content = msg.get("content", "")[:200]
                ctx_lines.append(f"{role}: {content}")
            if ctx_lines:
                user_input += f"\n\nContexto reciente:\n" + "\n".join(ctx_lines)

        user_input += "\n\nResponde ÚNICAMENTE con JSON válido."
        return user_input

    def _build_decompose_system_prompt(self, tenant_id: str) -> str:
        """Construir el sistema prompt para descomposición de tareas."""
        return f"""Eres un planificador de tareas de NeuralCrew Labs.

Descomponer una tarea compleja en subtasks específicas. Cada subtask debe:
- Tener un módulo asignado
- Tener una acción específica
- Tener parámetros claros

Responde ÚNICAMENTE con un array JSON de objetos con las claves:
- module: nombre del módulo
- action: acción específica
- params: parámetros de la subtask
- description: descripción breve

Ejemplo:
Input: "Crea una landing page y publícala en Instagram"
Output: [
    {{"module": "ai-web", "action": "generate", "params": {{...}}}},
    {{"module": "ai-social", "action": "publish", "params": {{...}}}}
]
"""

    def _build_extract_system_prompt(self, module: str, action: str) -> str:
        """Construir el sistema prompt para extracción de parámetros."""
        return f"""Eres un extractor de parámetros de NeuralCrew Labs.

Módulo: {module}
Acción: {action}

Extrae los parámetros relevantes del input del usuario y responda como JSON.
No inventes valores. Usa null para parámetros no proporcionados.
"""

    # =========================================================================
    # Construcción de mensajes con caching
    # =========================================================================

    def _build_cached_messages(
        self,
        system_prompt: str,
        user_message: str,
        use_cache: bool = False,
    ) -> list[dict[str, Any]]:
        """Construir array de mensajes con soporte para prompt caching."""
        messages = []

        if use_cache and "claude" in (settings.PRIMARY_MODEL or ""):
            # Claude prompt caching: dividir en system + user
            messages.append({
                "role": "system",
                "content": f"{system_prompt}\n{CACHE_BREAKPOINT}",
            })
            messages.append({
                "role": "user",
                "content": user_message,
            })
        else:
            # Modelo genérico: un solo sistema + usuario
            messages.append({
                "role": "system",
                "content": system_prompt,
            })
            messages.append({
                "role": "user",
                "content": user_message,
            })

        return messages

    # =========================================================================
    # Parsing de respuestas
    # =========================================================================

    def _parse_routing_response(self, data: dict) -> dict[str, Any]:
        """Parsear la respuesta del LLM para routing."""
        resp_content = ""
        try:
            # Safe access: handle None values from LLM
            message = data.get("choices", [{}])[0].get("message")
            if isinstance(message, dict):
                resp_content = message.get("content", "")
            if resp_content is None:
                resp_content = ""
        except (IndexError, AttributeError, KeyError):
            pass

        if not resp_content:
            logger.warning("Empty response content from LLM")
            return {
                "module": "ai-connect",
                "action": "send_message",
                "params": {},
                "confidence": 0.5,
                "reasoning": "Fallback por respuesta vacía del LLM",
            }

        try:
            result = json.loads(resp_content)
        except (json.JSONDecodeError, TypeError):
            safe_preview = resp_content if isinstance(resp_content, str) else "<None>"
            logger.warning(f"Failed to parse routing response as JSON: {safe_preview[:200]}")
            return {
                "module": "ai-connect",
                "action": "send_message",
                "params": {},
                "confidence": 0.5,
                "reasoning": "Fallback por parsing fallido",
            }


        # Validar y completar campos
        result.setdefault("module", "ai-connect")
        result.setdefault("action", "send_message")
        result.setdefault("params", {})
        result.setdefault("confidence", 0.5)
        result.setdefault("reasoning", "Decisión automática")
        result.setdefault("needs_decomposition", False)

        return result

    def _parse_decompose_response(self, data: dict) -> list[dict[str, Any]]:
        """Parsear la respuesta del LLM para descomposición."""
        content = ""
        if "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content") or ""

        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
            return []
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse decompose response as JSON: {content[:200]}")
            return []

    def _parse_extract_params_response(self, data: dict) -> dict[str, Any]:
        """Parsear la respuesta del LLM para extracción de parámetros."""
        content = ""
        if "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content") or ""

        try:
            result = json.loads(content)
            if isinstance(result, dict):
                return result
            return {}
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse extract params response as JSON: {content[:200]}")
            return {}

    # =========================================================================
    # Fallbacks
    # =========================================================================

    async def _route_with_fallback(self, prompt: str, tenant_id: str, history: list[dict] | None = None) -> dict[str, Any]:
        """Fallback de routing: siempre devuelve ai-connect si el LLM falla."""
        logger.warning("Using fallback routing: ai-connect.send_message")
        return {
            "module": "ai-connect",
            "action": "send_message",
            "params": {},
            "confidence": 0.3,
            "reasoning": "Fallback: LLM no disponible, usando ai-connect",
            "needs_decomposition": False,
        }

    async def _decompose_with_fallback(
        self, complex_prompt: str, tenant_id: str
    ) -> list[dict[str, Any]]:
        """Fallback de descomposición: una sola subtask con ai-connect."""
        logger.warning("Using fallback decomposition: single subtask ai-connect")
        return [
            {
                "module": "ai-connect",
                "action": "send_message",
                "params": {},
                "description": "Tarea procesada con fallback",
            }
        ]

    async def _extract_params_fallback(self, module: str, action: str, prompt: str) -> dict[str, Any]:
        """Fallback de extracción: retorna dict vacío."""
        logger.warning("Using fallback param extraction")
        return {"prompt_match": prompt[:100]}

    # =========================================================================
    # Cost tracking
    # =========================================================================

    def _record_llm_cost(self, model: str, data: dict, result: dict) -> None:
        """Registrar costo real basado en tokens usados."""
        try:
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0) or 0
            completion_tokens = usage.get("completion_tokens", 0) or 0

            cost = calculate_cost(prompt_tokens, completion_tokens, model)
            result["cost_usd"] = cost
            logger.debug(f"LLM cost: ${cost:.4f} for model {model}, {prompt_tokens + completion_tokens} tokens")
        except Exception as e:
            logger.warning(f"Failed to calculate LLM cost: {e}")
            result["cost_usd"] = 0.0


# Instancia global (singleton)
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Obtener el cliente de LLM (singleton)."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client