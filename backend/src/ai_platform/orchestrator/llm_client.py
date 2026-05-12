"""
Cliente OpenRouter para decisiones de orquestación.

Ragnar usa un LLM para decidir:
- Qué módulo ejecutar dado un input del usuario
- Qué parámetros extraer del input
- Cuánto contexto proporcionar a cada módulo

Modelos usados:
- claude-3.5-sonnet: Para decisiones complejas (routing, planning)
- gpt-4o-mini: Para tareas simples (categorización simple)
- openrouter/auto: Permite a OpenRouter elegir el mejor modelo

Patrones de optimización:
- Prompt caching para Claude (reduce costos 75%)
- Fallback routing si un modelo falla
- Timeout de 30 segundos por decisión
"""

import json
import logging
from typing import Any

import httpx

from ai_platform.core.config import get_settings
from ai_platform.orchestrator.mcp import get_mcp_client
from ai_platform.orchestrator.pricing import calculate_cost
from ai_platform.orchestrator.rate_limiter import get_rate_limit_tracker

logger = logging.getLogger(__name__)

settings = get_settings()

# Modelos disponibles para decisiones de orquestación
ROUTING_MODELS = {
    "primary": "anthropic/claude-3.5-sonnet",  # Mejor para decisiones complejas
    "fallback": "openai/gpt-4o-mini",  # Fallback más económico
    "fast": "google/gemini-2.0-flash-exp:free",  # Modelo gratuito para testing
}

# Timeout de 30 segundos por llamada LLM
LLM_TIMEOUT = 30.0

# Headers para prompt caching de Claude
# El header "anthropic-beta: prompt-caching-2024-07-31" habilita el caching
# Solo funciona con modelos Anthropic Claude
ANTHROPIC_CACHE_HEADER = {"anthropic-beta": "prompt-caching-2024-07-31"}

# Marcador de punto de cacheo para Claude
# Se coloca en el sistema para indicar dónde termina el contenido cacheable
CACHE_BREAKPOINT = "\n--- INICIO DEL PROMPT DEL SISTEMA (este contenido se cachea) ---"


class LLMClient:
    """
    Cliente OpenRouter para decisiones de orquestación.

    Encapsula las llamadas a LLM que Ragnar usa para:
    - Clasificar y enrutar tareas
    - Descomponer tareas complejas en subtasks
    - Extraer parámetros de los inputs de usuario
    - Tomar decisiones de coordinación entre módulos

    Uso:
        client = LLMClient()
        routing = await client.route_task({"prompt": "Generar un post para Instagram"})
        # routing = {"module": "ai-social", "params": {...}}
    """

    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient(
            base_url=self.settings.NAN_API_URL
            if self.settings.LLM_PROVIDER.lower() == "nan"
            else self.settings.OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {self.settings.NAN_API_KEY if self.settings.LLM_PROVIDER.lower() == 'nan' else self.settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Jemadiar1/ai-platform",
                "X-Title": "AI Platform - NeuralCrew Labs",
            },
            timeout=LLM_TIMEOUT,
        )
        # Tracker de límites de tasa para rate limiting
        self._rate_tracker = get_rate_limit_tracker()

    async def route_task(self, prompt: str, tenant_id: str, history: list[dict] | None = None) -> dict[str, Any]:
        """
        Decidir qué módulo debe ejecutar una tarea.

        Este es el método central de Ragnar. Usa Claude-3.5-Sonnet
        para analizar el prompt del usuario y decidir:
        1. Qué módulo es el más apropiado
        2. Qué acción dentro de ese módulo
        3. Qué parámetros relevantes extraer

        Parámetros:
            prompt: Input del usuario (ej: "Crear una landing page")
            tenant_id: ID del tenant actual
            history: Historial de conversación relevante

        Retorna:
            Dict con:
                - module: Nombre del módulo (ai-connect, ai-content, etc.)
                - action: Acción específica dentro del módulo
                - params: Parámetros extraídos del prompt
                - confidence: Score de confianza (0.0 - 1.0)
                - reasoning: Explicación de por qué eligió ese módulo
                - cost_usd: Costo real de la llamada (si se pudo rastrear)

        Raises:
            RuntimeError: Si no hay API key configurada
        """
        if self.settings.LLM_PROVIDER.lower() == "openrouter" and not self.settings.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY no está configurada. Verifica tu .env.")

        # Construir el prompt de sistema para la decisión
        system_prompt = self._build_routing_system_prompt(tenant_id, history)

        # Construir el mensaje del usuario
        user_message = self._build_routing_user_prompt(prompt, history)

        # Modelo a usar (primario para Claude con caching)
        model = self.settings.PRIMARY_MODEL or ROUTING_MODELS["primary"]
        is_claude = "claude" in model

        # Aplicar rate limiting antes de hacer la solicitud
        self._rate_tracker.wait_if_needed("openrouter")

        try:
            response = await self.client.post(
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": self._build_cached_messages(
                        system_prompt=system_prompt,
                        user_message=user_message,
                        use_cache=is_claude and self.settings.USE_PROMPT_CACHE,
                    ),
                    "max_tokens": 1024,
                    "temperature": 0.1,  # Baja temperatura para decisiones consistentes
                    "response_format": {"type": "json_object"},
                    # Headers para prompt caching (solo Claude)
                    **({"extra_headers": ANTHROPIC_CACHE_HEADER} if is_claude else {}),
                },
            )

            # Registrar la solicitud en el tracker de rate limits
            self._rate_tracker.record_request("openrouter", success=response.status_code == 200)

            if response.status_code == 200:
                data = response.json()
                result = self._parse_routing_response(data)
                # Registrar costo real basado en tokens
                self._record_llm_cost(model, data, result)
                return result

            logger.warning(
                f"Routing LLM failed with status {response.status_code}. Attempting fallback to gpt-4o-mini."
            )
            return await self._route_with_fallback(prompt, tenant_id, history)

        except httpx.TimeoutException:
            logger.warning("Routing LLM timed out. Using fallback.")
            self._rate_tracker.record_request("openrouter", success=False)
            return await self._route_with_fallback(prompt, tenant_id, history)
        except Exception as e:
            logger.error(f"Routing LLM error: {e}")
            self._rate_tracker.record_request("openrouter", success=False)
            return await self._route_with_fallback(prompt, tenant_id, history)

    async def decompose_task(self, complex_prompt: str, tenant_id: str) -> list[dict[str, Any]]:
        """
        Descomponer una tarea compleja en subtasks.

        Ejemplo:
            Input: "Crea una landing page y publícala en Instagram"
            Output: [
                {"module": "ai-web", "action": "generate", "params": {...}},
                {"module": "ai-content", "action": "create_copy", "params": {...}},
                {"module": "ai-social", "action": "publish", "params": {...}}
            ]

        Parámetros:
            complex_prompt: Input complejo del usuario
            tenant_id: ID del tenant actual

        Retorna:
            Lista de subtasks (cada una con module, action, params)
        """
        if self.settings.LLM_PROVIDER.lower() == "openrouter" and not self.settings.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY no está configurada. Verifica tu .env.")

        system_prompt = self._build_decompose_system_prompt(tenant_id)
        user_message = f"Decompone la siguiente tarea en pasos específicos:\n\n{complex_prompt}"

        model = self.settings.PRIMARY_MODEL or ROUTING_MODELS["primary"]
        is_claude = "claude" in model

        # Aplicar rate limiting antes de hacer la solicitud
        self._rate_tracker.wait_if_needed("openrouter")

        try:
            response = await self.client.post(
                "/v1/chat/completions",
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
                    # Headers para prompt caching (solo Claude)
                    **({"extra_headers": ANTHROPIC_CACHE_HEADER} if is_claude else {}),
                },
            )

            # Registrar la solicitud en el tracker de rate limits
            self._rate_tracker.record_request("openrouter", success=response.status_code == 200)

            if response.status_code == 200:
                data = response.json()
                result = self._parse_decompose_response(data)
                self._record_llm_cost(model, data, result)
                return result

            logger.warning("Decomposition LLM failed. Using fallback.")
            return await self._decompose_with_fallback(complex_prompt, tenant_id)

        except Exception as e:
            logger.error(f"Decomposition LLM error: {e}")
            self._rate_tracker.record_request("openrouter", success=False)
            return await self._decompose_with_fallback(complex_prompt, tenant_id)

    async def extract_params(self, prompt: str, module: str, action: str) -> dict[str, Any]:
        """
        Extraer parámetros relevantes de un input para un módulo específico.

        Ejemplo:
            Input: "Enviar un mensaje de WhatsApp a +51999999999: Hola, esto es una oferta"
            Module: ai-connect
            Action: send_whatsapp
            Output: {"phone": "+51999999999", "message": "Hola..."}

        Parámetros:
            prompt: Input del usuario
            module: Módulo objetivo
            action: Acción específica

        Retorna:
            Dict con parámetros extraídos
        """
        if self.settings.LLM_PROVIDER.lower() == "openrouter" and not self.settings.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY no está configurada. Verifica tu .env.")

        system_prompt = self._build_extract_system_prompt(module, action)
        user_message = f"Extrae los parámetros relevantes de este input:\n\n{prompt}"

        model = self.settings.FAST_MODEL or ROUTING_MODELS["fast"]
        is_claude = "claude" in model

        # Aplicar rate limiting antes de hacer la solicitud
        self._rate_tracker.wait_if_needed("openrouter")

        try:
            response = await self.client.post(
                "/v1/chat/completions",
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
                    # Headers para prompt caching (solo Claude)
                    **({"extra_headers": ANTHROPIC_CACHE_HEADER} if is_claude else {}),
                },
            )

            # Registrar la solicitud en el tracker de rate limits
            self._rate_tracker.record_request("openrouter", success=response.status_code == 200)

            if response.status_code == 200:
                data = response.json()
                result = self._parse_extract_response(data)
                self._record_llm_cost(model, data, result)
                return result

            return {}

        except Exception as e:
            logger.error(f"Extract params LLM error: {e}")
            self._rate_tracker.record_request("openrouter", success=False)
            return {}

    async def close(self) -> None:
        """Cerrar el cliente HTTP."""
        await self.client.aclose()

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _build_cached_messages(
        self,
        system_prompt: str,
        user_message: str,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Construir mensajes con soporte de prompt caching para Claude.

        Para modelos Anthropic Claude, se añaden los marcadores
        `cache_control: {"type": "ephemeral"}` que indican a Claude
        qué contenido debe cachearse.

        El sistema se cachea porque es contenido estático que se repite
        en cada llamada (misma configuración, mismas reglas).

        Los mensajes del usuario NO se cachean porque cambian en cada llamada.

        Patrones de Hermes:
        - System prompt: siempre cacheable (contenido estático)
        - User messages: no cacheables (contenido dinámico)
        - Cache breakpoint: marca el límite de lo que se cachea

        Parámetros:
            system_prompt: Prompt de sistema (se cachea si es Claude)
            user_message: Prompt del usuario (no se cachea)
            use_cache: Si está habilitado el caching

        Retorna:
            Lista de mensajes con cache_control donde aplica
        """
        if use_cache:
            return [
                {
                    "role": "system",
                    "content": system_prompt + CACHE_BREAKPOINT,
                    "cache_control": {"type": "ephemeral"},
                },
                {"role": "user", "content": user_message},
            ]
        else:
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

    def _record_llm_cost(
        self,
        model_name: str,
        response_data: dict,
        result: dict[str, Any],
    ) -> None:
        """
        Registrar el costo real de una llamada LLM basado en tokens usados.

        Lee los usage stats de la respuesta de OpenRouter y calcula
        el costo real usando los precios de pricing.py.

        Parámetros:
            model_name: Nombre del modelo usado
            response_data: Respuesta completa de OpenRouter
            result: Resultado parseado (para logging)
        """
        try:
            usage = response_data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            if input_tokens > 0 and output_tokens > 0:
                cost = calculate_cost(input_tokens, output_tokens, model_name)
                logger.info(
                    f"LLM usage: model={model_name}, "
                    f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
                    f"cost_usd={cost:.6f}"
                )
            else:
                logger.debug(f"LLM call completed but no usage data: model={model_name}")
        except Exception as e:
            logger.warning(f"Failed to record LLM cost: {e}")

    def _build_routing_system_prompt(self, tenant_id: str, history: list[dict] | None = None) -> str:
        """
        Construir el prompt de sistema para la decisión de routing.

        Este prompt define las reglas de decisión de Ragnar usando
        los principios de SOUL.md como guía.

        Este contenido se cachea en Claude (si está habilitado)
        porque es estático y se repite en cada llamada.
        """
        base = (
            "Ragnar es el orquestador principal de AI Platform. "
            "Tu trabajo es decidir qué módulo especializado debe ejecutar "
            "cada tarea del usuario.\n\n"
            "Módulos disponibles:\n"
            "- ai-connect: Mensajería (WhatsApp, Telegram, Slack, etc.)\n"
            "- ai-content: Generación de contenido (textos, posts, blogs)\n"
            "- ai-social: Gestión de redes sociales (Instagram, Facebook, LinkedIn)\n"
            "- ai-leads: Generación y gestión de leads\n"
            "- ai-ads: Campañas publicitarias (Meta Ads, Google Ads)\n"
            "- ai-analytics: Análisis de datos y métricas\n"
            "- ai-web: Generación de páginas web y landing pages\n\n"
            "Principios de decisión:\n"
            "1. Siempre selecciona UN SOLO módulo principal\n"
            "2. Si el usuario pide múltiples módulos, selecciona el principal y\n"
            "   marca 'needs_decomposition': true\n"
            "3. Piensa en el INTENT del usuario, no solo las palabras clave\n"
            "4. Si una tarea no encaja en ningún módulo, responde 'uncategorized'\n\n"
            "Debes responder SIEMPRE en este formato JSON:\n"
            "{\n"
            '  "module": "ai-connect" | "ai-content" | "ai-ads" | "ai-analytics" | "ai-leads" | "ai-social" | "ai-web" | "uncategorized",\n'
            '  "action": "string describing the specific action",\n'
            '  "confidence": 0.0 - 1.0,\n'
            '  "reasoning": "why this module was chosen",\n'
            '  "needs_decomposition": false\n'
            "}\n\n"
        )

        # Incluir herramientas MCP en el prompt
        try:
            mcp_client = get_mcp_client()
            tool_schemas = mcp_client.get_tool_schemas()
            if tool_schemas:
                base += "\n".join(tool_schemas) + "\n"
        except Exception as e:
            logger.warning(f"Failed to include MCP tools in routing prompt: {e}")

        if history:
            context = "Contexto de conversación relevante:\n"
            for msg in history[-5:]:  # Últimos 5 mensajes para contexto
                context += f"- {msg}\n"
            base += "\n" + context

        return base

    def _build_routing_user_prompt(self, prompt: str, history: list[dict] | None = None) -> str:
        """
        Construir el prompt del usuario para routing.
        """
        base = f"Usuario dice: {prompt}"

        if history:
            # Incluir contexto si disponible
            recent = history[-3:] if len(history) > 3 else history
            context = "\nHistorial reciente:\n"
            for msg in recent:
                context += f"- {msg}\n"
            base += context

        return base

    def _parse_routing_response(self, data: dict) -> dict[str, Any]:
        """
        Parsear la respuesta del LLM para routing.
        """
        try:
            content = data["choices"][0]["message"]["content"]
            routing = json.loads(content)

            return {
                "module": routing.get("module", "uncategorized"),
                "action": routing.get("action", "unknown"),
                "params": {},
                "confidence": min(max(routing.get("confidence", 0.5), 0.0), 1.0),
                "reasoning": routing.get("reasoning", ""),
                "needs_decomposition": routing.get("needs_decomposition", False),
            }
        except (KeyError, json.JSONDecodeError, IndexError) as e:
            logger.error(f"Failed to parse routing response: {e}")
            return {
                "module": "uncategorized",
                "action": "unknown",
                "params": {},
                "confidence": 0.0,
                "reasoning": "Failed to parse LLM response",
                "needs_decomposition": False,
            }

    def _build_decompose_system_prompt(self, tenant_id: str) -> str:
        """
        Construir el prompt para descomposición de tareas.
        """
        return (
            "Eres Ragnar, el orquestador de AI Platform. "
            "Tu trabajo es descomponer tareas complejas en pasos simples.\n\n"
            "Cada paso debe ser un módulo específico con su acción.\n"
            "Módulos: ai-connect, ai-content, ai-social, ai-leads, ai-ads, ai-analytics, ai-web\n\n"
            "Responde SIEMPRE en este formato JSON:\n"
            "{\n"
            '  "steps": [\n'
            '    {"module": "ai-connect", "action": "send_message", "params": {}, "depends_on": null},\n'
            '    {"module": "ai-social", "action": "post", "params": {}, "depends_on": 0}\n'
            "  ]\n"
            "}\n\n"
            "'depends_on' es el índice 0-based del paso que debe completarse antes.\n"
        )

    def _parse_decompose_response(self, data: dict) -> list[dict[str, Any]]:
        """
        Parsear la respuesta del LLM para descomposición.
        """
        try:
            content = data["choices"][0]["message"]["content"]
            response = json.loads(content)
            return response.get("steps", [])
        except (KeyError, json.JSONDecodeError, IndexError) as e:
            logger.error(f"Failed to parse decomposition response: {e}")
            return []

    def _build_extract_system_prompt(self, module: str, action: str) -> str:
        """
        Construir el prompt para extracción de parámetros.
        """
        return (
            f"Eras Ragnar, el orquestador de AI Platform.\n\n"
            f"El módulo '{module}' quiere ejecutar la acción '{action}'.\n"
            f"Extrae los parámetros relevantes del input del usuario.\n"
            f"Responde SIEMPRE en formato JSON válido.\n"
        )

    def _parse_extract_response(self, data: dict) -> dict[str, Any]:
        """
        Parsear la respuesta del LLM para extracción de parámetros.
        """
        try:
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, json.JSONDecodeError, IndexError) as e:
            logger.error(f"Failed to parse extract response: {e}")
            return {}

    # -------------------------------------------------------------------------
    # Fallback methods (sin LLM)
    # -------------------------------------------------------------------------

    async def _route_with_fallback(
        self, prompt: str, tenant_id: str, history: list[dict] | None = None
    ) -> dict[str, Any]:
        """
        Fallback: routing basado en reglas simples si el LLM falla.
        """
        return self._rule_based_routing(prompt)

    def _rule_based_routing(self, prompt: str) -> dict[str, Any]:
        """
        Routing basado en palabras clave como fallback.

        Este método no depende de LLM y siempre funciona.
        """
        prompt_lower = prompt.lower()

        if any(word in prompt_lower for word in ["whatsapp", "messenger", "telegram", "slack", "mensaje", "chat"]):
            return {
                "module": "ai-connect",
                "action": "send_message",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected messaging keywords",
                "needs_decomposition": False,
            }
        elif any(word in prompt_lower for word in ["landing", "webpage", "website", "página", "web"]):
            return {
                "module": "ai-web",
                "action": "generate_page",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected web page keywords",
                "needs_decomposition": False,
            }
        elif any(word in prompt_lower for word in ["post", "instagram", "facebook", "linkedin", "social", "publicar"]):
            return {
                "module": "ai-social",
                "action": "create_post",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected social media keywords",
                "needs_decomposition": False,
            }
        elif any(word in prompt_lower for word in ["ads", "advert", "campaign", "publicidad", "anuncio"]):
            return {
                "module": "ai-ads",
                "action": "create_campaign",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected ads keywords",
                "needs_decomposition": False,
            }
        elif any(word in prompt_lower for word in ["lead", "prospect", "cliente potencial", "contacto"]):
            return {
                "module": "ai-leads",
                "action": "generate_leads",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected leads keywords",
                "needs_decomposition": False,
            }
        elif any(word in prompt_lower for word in ["analytics", "report", "métrica", "estadística", "data"]):
            return {
                "module": "ai-analytics",
                "action": "generate_report",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected analytics keywords",
                "needs_decomposition": False,
            }
        elif any(word in prompt_lower for word in ["blog", "content", "copy", "texto", "artículo", "post", "generar"]):
            return {
                "module": "ai-content",
                "action": "generate_content",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected content generation keywords",
                "needs_decomposition": False,
            }

        return {
            "module": "uncategorized",
            "action": "unknown",
            "params": {},
            "confidence": 0.0,
            "reasoning": f"No matching keywords found in: {prompt}",
            "needs_decomposition": False,
        }

    async def _decompose_with_fallback(self, prompt: str, tenant_id: str) -> list[dict[str, Any]]:
        """
        Fallback: descomposición basada en reglas simples.
        """
        return [self._rule_based_routing(prompt)]
