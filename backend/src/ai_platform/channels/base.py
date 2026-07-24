"""
Clase base para todos los handlers de canales.

Implementa el patrón Template Method:
  handle_webhook(raw_payload) → validate → extract → decide → execute → send

Cada canal concreto (Telegram, Discord, WhatsApp) hereda de esta clase
y solo implementa los métodos específicos del canal.

"""

import asyncio
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class _RateLimiter:
    """
    Limitador de tasa simple basado en ventana deslizante.

    Implementa un algoritmo de token bucket con ventana de 1 segundo
    para prevenir que se excedan los límites de rate limiting de cada canal.

    Atributos:
        max_per_second: Número máximo de peticiones por segundo
        _timestamps: Diccionario con listas de timestamps por canal
    """

    def __init__(self, max_per_second: float = 10.0):
        """
        Inicializar el limitador de tasa.

        Parámetros:
            max_per_second: Máximo de peticiones por segundo por canal (default: 10)
        """
        self.max_per_second = max_per_second
        self._timestamps: defaultdict = defaultdict(list)

    async def acquire(self, channel_name: str):
        """
        Adquirir permiso para enviar un mensaje.

        Si se excedió el límite, espera hasta que haya espacio.

        Parámetros:
            channel_name: Nombre del canal para rate limiting por canal
        """
        now = asyncio.get_event_loop().time()
        window_start = now - 1.0

        # Eliminar timestamps fuera de la ventana de 1 segundo
        self._timestamps[channel_name] = [t for t in self._timestamps[channel_name] if t > window_start]

        # Si se excedió el límite, esperar
        if len(self._timestamps[channel_name]) >= self.max_per_second:
            sleep_time = 1.0 - (now - self._timestamps[channel_name][0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

        # Registrar el timestamp actual
        self._timestamps[channel_name].append(now)


class BaseChannel:
    """
    Clase base abstracta para handlers de canales.

    Cada canal debe implementar:
    - channel: nombre del canal ("telegram", "discord", "whatsapp")
    - send_message(chat_id, text): enviar respuesta al usuario
    - validate_webhook(payload): validar autenticidad del webhook
    - extract_message(raw_payload): extraer user_id, message_text, chat_id
    """

    channel: str = ""
    _rate_limiter: _RateLimiter = _RateLimiter(max_per_second=10.0)

    async def send_message(self, chat_id: str, text: str, **kwargs: Any) -> Any:
        """
        Enviar un mensaje de respuesta al usuario.

        Parámetros:
            chat_id: Identificador del chat/usuario en el canal
            text: Contenido del mensaje
            **kwargs: Parámetros específicos del canal (formato, buttons, etc.)

        Retorna:
            Resultado de la API del canal (message_id, etc.)
        """
        ...

    async def validate_webhook(self, payload: Any, headers: dict | None = None) -> dict:
        """
        Validar que el webhook es auténtico.

        Parámetros:
            payload: Payload crudo del webhook
            headers: Diccionario con los headers HTTP (opcional)

        Retorna:
            Dict con claves:
                - valid: bool, si el webhook es válido
                - reason: str, razón de invalidación si aplica
        """
        ...

    async def extract_message(self, raw_payload: Any) -> dict[str, str]:
        """
        Extraer información del mensaje del payload del canal.

        Parámetros:
            raw_payload: Payload crudo del webhook

        Retorna:
            Dict con claves:
                - user_id: str, ID del usuario en el canal
                - user_name: str, nombre del usuario
                - message_text: str, texto del mensaje
                - chat_id: str, ID del chat para responder
        """
        ...

    async def handle_webhook(
        self,
        raw_payload: Any,
        tenant_id: str,
        session_manager=None,
        odin_inst=None,
    ) -> dict[str, Any]:
        """
        Manejar un webhook completo: validar → extraer → Odin → enviar respuesta.

        Este es el método template que orquesta todo el flujo:
        1. Validar webhook (autenticidad)
        2. Extraer mensaje (user_id, text, chat_id)
        3. Buscar o crear mapeo de canal a usuario de plataforma
        4. Llamar a Odin.decide() para routing
        5. Ejecutar el módulo seleccionado
        6. Enviar respuesta al canal
        7. Guardar mensaje en la tabla messages

        Parámetros:
            raw_payload: Payload crudo del webhook del canal
            tenant_id: ID del tenant actual
            session_manager: SessionManager para gestionar sesiones
            Odin: Instancia de Odin para decisiones de routing

        Retorna:
            Dict con resultado del procesamiento
        """
        # Paso 1: Validar webhook
        validation = await self.validate_webhook(raw_payload)
        if not validation.get("valid"):
            logger.warning(f"Webhook inválido para canal {self.channel}: {validation.get('reason')}")
            return {"status": "error", "message": "Webhook no validado"}

        # Paso 2: Extraer mensaje del payload
        extracted = await self.extract_message(raw_payload)
        user_id = extracted["user_id"]
        user_name = extracted["user_name"]
        message_text = extracted["message_text"]
        chat_id = extracted["chat_id"]

        if not message_text:
            logger.info(f"Mensaje vacío de canal {self.channel}, ignorando")
            return {"status": "ignored", "reason": "empty_message"}

        logger.info(f"Mensaje de {self.channel}: user={user_id}, chat={chat_id}, text={message_text[:100]}")

        # Paso 3: Buscar o crear mapeo de canal → usuario de plataforma
        from ai_platform.database import make_session
        from ai_platform.models.channel_mapping import (
            get_or_create_channel_mapping,
        )

        mapping = None
        platform_user_id = None
        platform_tenant_id = tenant_id

        with make_session() as db:
            mapping = get_or_create_channel_mapping(
                db=db,
                tenant_id=platform_tenant_id,
                channel=self.channel,
                channel_user_id=user_id,
                channel_username=user_name,
                channel_chat_id=chat_id,
            )
            platform_user_id = str(mapping.user_id) if mapping else None

        # Paso 4: Llamar a Odin.decide()
        if not odin_inst:
            from ai_platform.orchestrator.odin import get_odin

            odin_inst = get_odin()

        try:
            decision = await odin_inst.decide(
                prompt=message_text,
                tenant_id=platform_tenant_id,
                user_id=platform_user_id,
                session_id=None,
            )
        except Exception as e:
            logger.error(f"Error en Odin.decide(): {e}")
            await self.send_message(chat_id, "Lo siento, hubo un error procesando tu mensaje. Intenta de nuevo.")
            return {"status": "error", "message": str(e)}

        module = decision["module"]
        session_id = decision["session_id"]

        logger.info(
            f"Decisión de Odin: module={module}, action={decision['action']}, confidence={decision['confidence']:.2f}"
        )

        # Paso 5: Ejecutar el módulo seleccionado (síncrono, no Celery)
        module_result = await self._execute_module_sync(odin_inst, decision, str(mapping.tenant_id))

        # Paso 6: Construir respuesta para el usuario
        if module_result.get("status") == "success" or module_result.get("status") == "completed":
            response_text = self._format_response_text(module_result)
        else:
            error_msg = module_result.get("error", "Error desconocido en el módulo")
            response_text = f"Lo siento, hubo un error: {error_msg}"

        # Paso 7: Enviar respuesta al canal
        try:
            chunks = self._chunk_message(response_text)
            for i, chunk in enumerate(chunks):
                await self._rate_limiter.acquire(self.channel)
                await self.send_message(chat_id, chunk)
                if i < len(chunks) - 1:
                    await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Error enviando respuesta a {self.channel}: {e}")

        # Paso 8: Guardar mensajes en la tabla messages
        try:
            if session_manager:
                await session_manager.add_message(
                    session_id=session_id,
                    role="user",
                    content=message_text,
                    token_count=len(message_text) // 4,
                )
                await session_manager.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=response_text,
                    token_count=len(response_text) // 4,
                )
        except Exception as e:
            logger.error(f"Error guardando mensajes en BD: {e}")

        return {
            "status": "success",
            "channel": self.channel,
            "user_id": user_id,
            "chat_id": chat_id,
            "session_id": session_id,
            "module": module,
            "action": decision["action"],
        }

    async def _execute_module_sync(
        self,
        odin_inst: Any,
        decision: dict[str, Any],
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        Ejecutar el módulo seleccionado de forma síncrona.

        Reutiliza la lógica de Odin._invoke_module() pero ejecuta
        de forma síncrona sin pasar por Celery.

        Parámetros:
            Odin: Instancia de Odin
            decision: Decisión de routing
            tenant_id: ID del tenant

        Retorna:
            Dict con resultado de la ejecución
        """
        module = decision["module"]
        params = decision["params"]

        from ai_platform.orchestrator.modules import get_handler

        HandlerClass = get_handler(module)
        if HandlerClass is None:
            return {
                "module": module,
                "status": "error",
                "error": f"Módulo no soportado: {module}",
            }

        try:
            handler_instance = HandlerClass()
            result = handler_instance.execute({**params, "tenant_id": tenant_id})

            return result

        except Exception as e:
            logger.error(f"Error ejecutando módulo {module}: {e}")
            return {
                "module": module,
                "status": "error",
                "error": str(e),
            }

    def _format_response_text(self, result: dict[str, Any]) -> str:
        """
        Formatear el resultado del módulo como texto legible.

        Parámetros:
            result: Resultado del módulo

        Retorna:
            Texto formateado para enviar al usuario
        """
        if isinstance(result, dict):
            response_data = result.get("result", result.get("response", result))
            if isinstance(response_data, dict):
                return response_data.get("message", str(response_data))
            elif isinstance(response_data, str):
                return response_data
            return str(result)
        return str(result)

    def _chunk_message(self, text: str, max_length: int = 4096) -> list[str]:
        """
        Dividir un mensaje largo en chunks que quepan en el límite del canal.

        Busca saltos de línea para dividir de forma limpia.

        Parámetros:
            text: Texto original
            max_length: Límite de caracteres del canal

        Retorna:
            Lista de chunks
        """
        if len(text) <= max_length:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= max_length:
                chunks.append(remaining)
                break

            # Buscar un buen punto de corte (salto de línea o espacio)
            chunk = remaining[:max_length]
            split_pos = chunk.rfind("\n")
            if split_pos == -1 or split_pos < max_length // 2:
                split_pos = chunk.rfind(" ")
            if split_pos == -1 or split_pos < max_length // 2:
                split_pos = max_length

            chunks.append(remaining[:split_pos].rstrip())
            remaining = remaining[split_pos:].lstrip()

        return chunks
