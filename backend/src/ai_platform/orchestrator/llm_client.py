"""
Cliente OpenRouter para decisiones de orquestación.

Odin usa un LLM para decidir:
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

import base64
import base64
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
    "primary": "qwen3.6",  # Modelo por defecto NAN
    "fallback": "qwen3.6",  # Fallback NAN
    "fast": "qwen3.6",  # Modelo rápido NAN
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

    Encapsula las llamadas a LLM que Odin usa para:
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
        # NAN API uses /chat/completions (no /v1 prefix in path)
        self._chat_path = "/chat/completions" if self.settings.LLM_PROVIDER.lower() == "nan" else "/v1/chat/completions"
        # Tracker de límites de tasa para rate limiting
        self._rate_tracker = get_rate_limit_tracker()

    async def route_task(
        self,
        prompt: str,
        tenant_id: str,
        history: list[dict] | None = None,
        memory_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Decidir qué módulo debe ejecutar una tarea.

        Este es el método central de Odin. Usa Claude-3.5-Sonnet
        para analizar el prompt del usuario y decidir:
        1. Qué módulo es el más apropiado
        2. Qué acción dentro de ese módulo
        3. Qué parámetros relevantes extraer

        Parámetros:
            prompt: Input del usuario (ej: "Crear una landing page")
            tenant_id: ID del tenant actual
            history: Historial de conversación relevante
            memory_context: Contexto de memoria con cross_session_user

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
        user_profile = ""
        if memory_context:
            user_profile = memory_context.get("cross_session_user", "")

        system_prompt = self._build_routing_system_prompt(tenant_id, history, user_profile=user_profile)

        # Construir el mensaje del usuario
        user_message = self._build_routing_user_prompt(prompt, history)

        # Modelo a usar (primario para Claude con caching)
        model = self.settings.PRIMARY_MODEL or ROUTING_MODELS["primary"]
        is_claude = "claude" in model

        # Aplicar rate limiting antes de hacer la solicitud
        self._rate_tracker.wait_if_needed("openrouter")

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

    def _build_routing_system_prompt(
        self,
        tenant_id: str,
        history: list[dict] | None = None,
        user_profile: str = "",
    ) -> str:
        """
        Construir el prompt de sistema para la decisión de routing.

        Este prompt define las reglas de decisión de Odin usando
        los principios de SOUL.md como guía.

        Este contenido se cachea en Claude (si está habilitado)
        porque es estático y se repite en cada llamada.
        """
        base = (
            "Odin es el orquestador principal de AI Platform. "
            "Tu trabajo es decidir qué módulo especializado debe ejecutar "
            "cada tarea del usuario.\n\n"
            "Módulos disponibles:\n"
            "- ai-connect: Mensajería (WhatsApp, Telegram, Slack, etc.)\n"
            "- ai-content: Generación de contenido (textos, posts, blogs)\n"
            "- ai-social: Gestión de redes sociales (Instagram, Facebook, LinkedIn)\n"
            "- ai-leads: Generación y gestión de leads\n"
            "- ai-ads: Campañas publicitarias (Meta Ads, Google Ads)\n"
            "- ai-analytics: Análisis de datos, investigación web, OCR, chunking y búsqueda en documentos\n"
            "- ai-documents: Generación de archivos profesionales (DOCX, XLSX, PPTX, PDF, imágenes)\n"
            "- ai-web: Generación de páginas web y landing pages\n\n"
            "Principios de decisión:\n"
            "1. Siempre selecciona UN SOLO módulo principal\n"
            "2. Si el usuario pide múltiples módulos, selecciona el principal y marca 'needs_decomposition': true\n"
            "3. Piensa en el INTENT del usuario, no solo las palabras clave\n"
            "4. Si una tarea no encaja en ningún módulo, responde 'uncategorized'\n\n"
            "Debes responder SIEMPRE en este formato JSON:\n"
            "{\n"
            '  "module": "ai-connect" | "ai-content" | "ai-ads" | "ai-analytics" | "ai-documents" | "ai-leads" | "ai-social" | "ai-web" | "uncategorized",\n'
            '  "action": "string describing the specific action",\n'
            '  "confidence": 0.0 - 1.0,\n'
            '  "reasoning": "why this module was chosen",\n'
            '  "needs_decomposition": false\n'
            "}\n\n"
        )

        # Add user profile context if available
        if user_profile:
            base += f"\n## Perfil del Usuario\n{user_profile}\n\n"

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
            "Eres Odin, el orquestador de AI Platform. "
            "Tu trabajo es descomponer tareas complejas en pasos simples.\n\n"
            "Cada paso debe ser un módulo específico con su acción.\n"
            "Módulos: ai-connect, ai-content, ai-social, ai-leads, ai-ads, ai-analytics, ai-web, ai-documents\n\n"
            "Acciones por módulo:\n"
            "ai-connect: send_message, make_voice_call, schedule_appointment, handle_chat_message, update_contact, get_contacts\n"
            "ai-content: generate_content, default\n"
            "ai-social: create_post, analyze_engagement, default\n"
            "ai-leads: generate_leads, default\n"
            "ai-ads: create_campaign, default\n"
            "ai-analytics: web_research, web_fetch, web_browser, ocr_extract, chart_detect, chart_analyze, image_describe, document_understand, document_ingest, document_chunk, document_fts_search, generate_report, render_report, default\n"
            "ai-web: generate_page, default\n"
            "ai-documents: render_docx, render_xlsx, render_pptx, render_png, render_pdf, render_all, default\n\n"
            "Responde SIEMPRE en este formato JSON:\n"
            "{\n"
            '  "steps": [\n'
            '    {"module": "ai-connect", "action": "send_message", "params": {}, "depends_on": null},\n'
            '    {"module": "ai-social", "action": "create_post", "params": {}, "depends_on": 0}\n'
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
            f"Eras Odin, el orquestador de AI Platform.\n\n"
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
        elif any(
            word in prompt_lower
            for word in ["generar docx", "generar pptx", "generar xlsx", "generar pdf", "generar png",
                         "crear docx", "crear pptx", "crear xlsx", "crear pdf", "crear png",
                         "crear documento", "crear presentación", "crear hoja de cálculo", "crear imagen",
                         "render docx", "render pptx", "render xlsx", "render pdf", "render png",
                         "professional doc", "professional pptx", "professional xlsx", "professional pdf",
                         "generate docx", "generate pptx", "generate xlsx", "generate pdf", "generate png",
                         "generate document", "generate presentation", "generate spreadsheet", "generate image",
                         "crear presentación", "crear documento profesional", "crear infografía",
                         "generar reporte profesional", "generar presentación", "generar documento"]
        ):
            return {
                "module": "ai-documents",
                "action": "render_all",
                "params": {},
                "confidence": 0.8,
                "reasoning": "Rule-based: detected professional document generation keywords",
                "needs_decomposition": False,
            }
        elif any(
            word in prompt_lower
            for word in ["document", "upload", "subir", "pdf", "docx", "chunk", "index", "fts", "search doc",
                         "ingest", "ingestion", "process document", "analyze document from file",
                         "sube el documento", "procesa el archivo", "extrae texto del pdf"]
        ):
            return {
                "module": "ai-analytics",
                "action": "document_ingest",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected document ingestion keywords",
                "needs_decomposition": False,
            }
        elif any(
            word in prompt_lower for word in ["ocr", "scan", "escanear", "extract text image", "chart detect", "graph"]
        ):
            return {
                "module": "ai-analytics",
                "action": "ocr_extract",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected OCR/visual analysis keywords",
                "needs_decomposition": False,
            }
        elif any(
            word in prompt_lower
            for word in ["research", "investigar", "web search", "buscar web", "fetch url", "scrape"]
        ):
            return {
                "module": "ai-analytics",
                "action": "web_research",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected web research keywords",
                "needs_decomposition": False,
            }
        elif any(
            word in prompt_lower
            for word in ["report", "render", "generate report", "export report", "pdf report", "xlsx", "spreadsheet"]
        ):
            return {
                "module": "ai-analytics",
                "action": "render_report",
                "params": {},
                "confidence": 0.7,
                "reasoning": "Rule-based: detected report rendering keywords",
                "needs_decomposition": False,
            }

        return {
            "module": "ai-connect",
            "action": "send_message",
            "params": {},
            "confidence": 0.5,
            "reasoning": "Default routing: no specific keywords matched, using ai-connect as fallback",
            "needs_decomposition": False,
        }

    async def _decompose_with_fallback(self, prompt: str, tenant_id: str) -> list[dict[str, Any]]:
        """
        Fallback: descomposición basada en reglas simples.
        """
        return [self._rule_based_routing(prompt)]

    @staticmethod
    def encode_image_to_base64(image_bytes: bytes) -> str:
        """Convert image bytes to base64 data URL.

        Parámetros:
            image_bytes: Raw bytes of the image

        Retorna:
            data URL string: data:image/png;base64,iVBOR...
        """
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:image/png;base64,{encoded}"

    async def vision_chat(
        self, prompt: str, image_bytes: bytes, *, tenant_id: str = ""
    ) -> dict[str, Any]:
        """
        Enviar una imagen + prompt a un LLM multimodal (vision).

        Construye un mensaje multimodal con formato OpenAI compatible:
        [
            {"type": "text", "text": "¿Qué ves?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]

        La imagen se codifica a base64 y se envía junto al prompt de texto.
        El modelo interpreta la imagen textualmente.

        Parámetros:
            prompt: Pregunta o instrucción sobre la imagen
            image_bytes: Bytes de la imagen (PNG, JPG, etc.)
            tenant_id: ID del tenant (para logging)

        Retorna:
            Dict con 'text' (respuesta del modelo) y 'model' usado
        """
        if not image_bytes:
            logger.warning("vision_chat called with empty image_bytes")
            return {
                "text": "No se recibió imagen para analizar",
                "model": self.settings.VISION_MODEL,
            }

        try:
            encoded = self.encode_image_to_base64(image_bytes)
        except Exception as e:
            logger.error(f"Error encoding image to base64: {e}")
            return {"text": "Error al procesar la imagen", "model": self.settings.VISION_MODEL}

        model = self.settings.VISION_MODEL or "mimo-v2.5"
        max_retries = 2

        for attempt in range(max_retries):
            try:
                response = await self.client.post(
                    self._chat_path,
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": encoded},
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 2048,
                        "temperature": 0.3,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    logger.info(
                        f"Vision chat OK: model={model}, attempt={attempt+1}, "
                        f"text_len={len(content)}"
                    )
                    if content and content.strip():
                        return {"text": content.strip(), "model": model}
                    return {"text": "", "model": model}

                logger.warning(
                    f"vision_chat({model}) attempt {attempt+1}/{max_retries} "
                    f"failed: {response.status_code}"
                )

                # Retry with secondary model on second attempt
                if attempt == 0 and self.settings.VISION_MODEL_SECONDARY:
                    model = self.settings.VISION_MODEL_SECONDARY
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
                    self._chat_path = "/chat/completions" if self.settings.LLM_PROVIDER.lower() == "nan" else "/v1/chat/completions"
                    continue

            except Exception as e:
                logger.error(f"vision_chat attempt {attempt+1} error: {e}")
                if attempt == 0 and self.settings.VISION_MODEL_SECONDARY:
                    model = self.settings.VISION_MODEL_SECONDARY
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
                    self._chat_path = "/chat/completions" if self.settings.LLM_PROVIDER.lower() == "nan" else "/v1/chat/completions"
                    continue

        logger.error(f"vision_chat failed after {max_retries} attempts")
        return {
            "text": "Lo siento, no pude analizar la imagen. Intenta de nuevo.",
            "model": "error",
        }

    def chat(self, prompt: str, tenant_id: str = "", user_id: str = "") -> dict[str, Any]:
        """
        Enviar un mensaje al LLM y obtener una respuesta.

        Este método es síncrono y se usa para generar respuestas de chat
        cuando el módulo ai-connect recibe una acción send_message.
        """
        model = self.settings.PRIMARY_MODEL or "qwen3.6"
        response = None

        try:
            with httpx.Client(
                base_url=self.settings.NAN_API_URL
                if self.settings.LLM_PROVIDER.lower() == "nan"
                else self.settings.OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {self.settings.NAN_API_KEY if self.settings.LLM_PROVIDER.lower() == 'nan' else self.settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=60,
            ) as client:
                response = client.post(
                    "/chat/completions",
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": f"Eres un asistente de marketing digital de NeuralCrew Labs, una agencia 100% potenciada por IA. Responde de forma útil, concisa y profesional en español. Usuario: {prompt}",
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
                    content = choice.get("message", {}).get("content", "")

                if content and content.strip():
                    _truncated = choice.get("finish_reason") == "length"
                    result = {"content": content.strip(), "model": model, "_truncated": _truncated}
                    if _truncated:
                        logger.warning(
                            f"Response truncated, consider increasing max_tokens. Prompt: {len(prompt)} chars"
                        )
                    return result
        except Exception as e:
            logger.error(f"Chat LLM error: {e}")
            return {
                "content": "Lo siento, estoy teniendo problemas para generar una respuesta. Intenta de nuevo.",
                "model": model,
            }
