"""
Webhooks de canales (Telegram, Discord, WhatsApp).

Endpoint único para enrutar mensajes entrantes desde canales de comunicación
al orquestador Odin, que decide qué módulo de negocio ejecutar.

"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

from ai_platform.models.db import Tenant

router = APIRouter()


# ============================================================================
# Webhooks de Canales (Telegram, Discord, WhatsApp)
# ============================================================================


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    """
    Endpoint de webhook de Telegram.

    Recepción de mensajes entrantes desde Telegram Bot API.

    Configuración:
    1. Crear bot con @BotFather → copiar token
    2. Configurar webhook: curl -X POST "https://api.telegram.org/bot{token}/setWebhook" -d "url=<api>/api/v1/webhooks/telegram"
    3. Poner token en TELEGRAM_BOT_TOKEN (variable de entorno)
    """
    from ai_platform.channels.telegram import TelegramChannel

    logger = logging.getLogger(__name__)

    payload_bytes = await request.body()
    update_data = json.loads(payload_bytes)
    channel = TelegramChannel()

    # Validar webhook
    validation = await channel.validate_webhook(update_data, dict(request.headers))
    if not validation.get("valid"):
        logger.warning(f"Telegram webhook no validado: {validation.get('reason')}")
        return {"status": "rejected", "reason": validation.get("reason")}

    # Extraer datos del mensaje
    message = update_data.get("message", {})
    text = message.get("text", "")
    if not text:
        return {"status": "ignored", "reason": "mensaje_sin_texto"}

    user = message.get("from", {})
    chat = message.get("chat", {})

    user_id = str(user.get("id", ""))
    user_name = user.get("first_name", "unknown")
    chat_id = str(chat.get("id", ""))

    logger.info(f"Mensaje entrante Telegram: user={user_id}, text={text[:100]}")

    return await _process_channel_message(
        channel="telegram",
        user_id=user_id,
        user_name=user_name,
        chat_id=chat_id,
        message_text=text,
    )


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Endpoint de webhook de WhatsApp (Meta Business API).

    Maneja 2 flujos:
    1. Verificación del webhook (GET con challenge)
    2. Mensajes entrantes (POST con datos de mensaje)

    Configuración:
    1. Configurar app en Meta Developer → WhatsApp
    2. Callback URL: <tu-api>/api/v1/webhooks/whatsapp
    3. Verify Token: poner en WHATSAPP_WEBHOOK_VERIFY_TOKEN
    """
    from ai_platform.channels.whatsapp_channel import WhatsAppChannel

    logger = logging.getLogger(__name__)

    if request.method == "GET":
        # Verificación de webhook (Meta envía GET)
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")

        from ai_platform.core.config import get_settings

        settings = get_settings()

        if mode == "verify" and token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
            logger.info("Webhook de WhatsApp verificado exitosamente")
            return {"status": "verified", "challenge": challenge}

        return {"status": "rejected", "reason": "validación fallida"}

    # Mensajes entrantes (POST)
    payload = await request.body()
    channel = WhatsAppChannel()

    # Validar firma HMAC-SHA256
    validation = await channel.validate_webhook(payload, dict(request.headers))
    if not validation.get("valid"):
        logger.warning(f"WhatsApp webhook no validado: {validation.get('reason')}")
        return {"status": "rejected", "reason": validation.get("reason", "firma_invalida")}

    import json

    update_data = json.loads(payload)

    # Extraer mensaje del payload de Meta
    extracted = channel.extract_message(update_data)

    if extracted.get("error"):
        return {"status": "error", "message": extracted["error"]}

    user_id = extracted.get("user_id", "")
    user_name = extracted.get("user_name", "unknown")
    chat_id = extracted.get("chat_id", "")
    message_text = extracted.get("message_text", "")

    logger.info(f"Mensaje entrante WhatsApp: user={user_id}, text={message_text[:100]}")

    return await _process_channel_message(
        channel="whatsapp",
        user_id=user_id,
        user_name=user_name,
        chat_id=chat_id,
        message_text=message_text,
    )


@router.post("/webhooks/discord")
async def discord_webhook(request: Request):
    """
    Endpoint de webhook de Discord (Interactions API).

    Maneja interacciones de Discord (slash commands y mensajes directos).

    Configuración:
    1. Crear bot en Discord Developer Portal → copiar token
    2. Configurar Interactions Endpoint URL: <tu-api>/api/v1/webhooks/discord
    3. Interactions Public Key: poner en variable de entorno (opcional)
    4. Poner DISCORD_BOT_TOKEN en variables de entorno
    """
    from ai_platform.channels.discord import DiscordChannel

    logger = logging.getLogger(__name__)
    payload = await request.body()

    channel = DiscordChannel()

    # Validar webhook de Discord
    validation = await channel.validate_webhook(payload, dict(request.headers))
    if not validation.get("valid"):
        logger.warning(f"Discord webhook no validado: {validation.get('reason')}")
        return {"status": "rejected", "reason": validation.get("reason")}

    import json

    update_data = json.loads(payload)

    # Extraer usuario y mensaje según tipo de interacción
    user = update_data.get("member", {}).get("user", update_data.get("user", {}))
    message = update_data.get("message", {})
    data = update_data.get("data", {})

    user_id = str(user.get("id", ""))
    user_name = user.get("username", user.get("global_name", "unknown"))
    chat_id = str(update_data.get("channel_id", message.get("channel_id", "")))

    # Obtener texto del mensaje/interacción
    if data.get("options"):
        # Slash command con opciones
        message_text = data["options"][0].get("value", "") or data.get("content", "")
    else:
        message_text = update_data.get("content", "") or data.get("content", "")

    if not message_text:
        return {"status": "ignored", "reason": "no_content"}

    logger.info(f"Mensaje entrante Discord: user={user_id}, text={message_text[:100]}")

    return await _process_channel_message(
        channel="discord",
        user_id=user_id,
        user_name=user_name,
        chat_id=chat_id,
        message_text=message_text,
    )


# ============================================================================
# Funciones auxiliares
# ============================================================================


async def _process_channel_message(
    channel: str,
    user_id: str,
    user_name: str,
    chat_id: str,
    message_text: str,
) -> dict[str, Any]:
    """
    Procesar mensaje de cualquier canal de forma unificada.

    Este método conecta el webhook del canal con el flujo de Odin completo:
    1. Buscar o crear mapeo de canal → usuario de plataforma
    2. Llamar a Odin.decide() para routing del módulo
    3. Ejecutar el módulo seleccionado
    4. Enviar respuesta de vuelta al canal

    Parámetros:
        channel: Canal ("telegram", "discord", "whatsapp")
        user_id: ID del usuario en el canal externo
        user_name: Nombre del usuario en el canal
        chat_id: Identificador del chat para responder
        message_text: Texto del mensaje del usuario

    Retorna:
        Dict con resultado del proceso
    """
    from ai_platform.database import make_session
    from ai_platform.models.channel_mapping import get_channel_user_info
    from ai_platform.orchestrator.odin import get_odin

    odin_inst = get_odin()

    # Paso 1: Buscar mapeo de canal externo → usuario de plataforma (sin tenant_id)
    with make_session() as db:
        mapping = get_channel_user_info(
            channel=channel,
            channel_user_id=user_id,
        )

        if not mapping:
            # Primer mensaje: crear mapeo sin tenant_id específico
            from ai_platform.models.channel_mapping import create_fallback_channel_mapping

            mapping = create_fallback_channel_mapping(
                db=db,
                channel=channel,
                channel_user_id=user_id,
                channel_username=user_name,
                channel_chat_id=chat_id,
            )

    if not mapping:
        return {"status": "error", "message": "No se pudo crear mapeo de canal"}

    logger = logging.getLogger(__name__)

    # Resolver tenant_id: si es None, crear/obtener tenant por defecto para canales
    if mapping.tenant_id is None:
        from uuid import uuid4

        from ai_platform.database import Base, engine

        # Asegurar que todas las tablas existen (puede que no se hayan creado en VPS)
        Base.metadata.create_all(engine)

        default_tenant_slug = "telegram-default"
        with make_session() as db:
            default_tenant = db.execute(
                text("""
                    SELECT id FROM tenants WHERE slug = :slug LIMIT 1
                """),
                {"slug": default_tenant_slug},
            ).first()

            if not default_tenant:
                default_tenant_id = uuid4()
                db.execute(
                    text("""
                        INSERT INTO tenants (id, name, slug, plan, is_active, created_at)
                        VALUES (:id, 'NeuralCrew Labs', :slug, 'starter', true, NOW())
                    """),
                    {"id": default_tenant_id, "slug": default_tenant_slug},
                )
                db.commit()
                logger.info(f"Tenant por defecto creado: {default_tenant_id}")
                tenant_id = str(default_tenant_id)
            else:
                tenant_id = str(default_tenant.id)

            # Actualizar el mapping con el tenant_id resuelto
            db.execute(
                text("""
                    UPDATE channel_mappings
                    SET tenant_id = :tenant_id
                    WHERE id = :mapping_id
                """),
                {"tenant_id": default_tenant.id if default_tenant else default_tenant_id, "mapping_id": mapping.id},
            )
            db.commit()
            # Recargar mapping con el tenant_id actualizado
            mapping = get_channel_user_info(channel=channel, channel_user_id=user_id)
    else:
        tenant_id = str(mapping.tenant_id)

    user_id_platform = str(mapping.user_id) if mapping.user_id else None

    # Paso 2: Resolver session por channel_user_id (reutilizar sesión activa si existe)
    from ai_platform.orchestrator.session import get_session_manager

    session_mgr = get_session_manager()
    resolved_session_id = await session_mgr.resolve_session_for_user(
        tenant_id=tenant_id,
        channel_user_id=user_id,
    )

    # Paso 2.5: Cerrar sesiones idle del mismo usuario si están expiradas
    try:
        await session_mgr.close_idle_sessions(tenant_id=tenant_id, channel_user_id=user_id)
    except Exception:
        pass

    try:
        decision = await odin_inst.decide(
            prompt=message_text,
            tenant_id=tenant_id,
            user_id=user_id_platform,
            session_id=resolved_session_id,
        )
    except Exception as e:
        logger.error(f"Error en Odin.decide(): {e}")
        await _send_channel_error(channel, chat_id, "Error interno")
        return {"status": "error", "message": str(e)}

    session_id = decision.get("session_id")
    module_name = decision["module"]
    action = decision["action"]
    params = decision.get("params", {})

    # Paso 3: Actualizar session_id en channel_mappings para reutilización futura
    if session_id and mapping:
        with make_session() as db:
            db.execute(
                text("""
                    UPDATE channel_mappings
                    SET last_session_id = :session_id
                    WHERE id = :mapping_id
                """),
                {"session_id": session_id, "mapping_id": mapping.id},
            )
            db.commit()

    # Paso 4: Actualizar chat_id en el mapeo de canal
    if session_id:
        channel_update_channel(
            session_id=session_id,
            channel=channel,
            chat_id=chat_id,
            channel_user_id=user_id,
        )

    # Paso 4: Ejecutar el módulo seleccionado
    try:
        module_result = await _execute_module(
            module_name=module_name,
            action=action,
            params=params,
            tenant_id=tenant_id,
            user_id=user_id_platform,
            channel=channel,
            chat_id=chat_id,
            message_text=message_text,
        )
    except Exception as e:
        logger.error(f"Error ejecutando módulo {module_name}: {e}")
        await _send_channel_error(channel, chat_id, "Error procesando tu solicitud")
        return {
            "status": "error",
            "message": f"Error ejecutando módulo {module_name}: {e!s}",
            "module": module_name,
        }

    # Paso 5: Enviar respuesta de vuelta al canal
    response_text = _extract_response_text(module_result)
    if response_text:
        await _send_to_channel(channel, chat_id, response_text)

    return {
        "status": "success",
        "channel": channel,
        "module": module_name,
        "session_id": session_id,
        "action": action,
        "confidence": decision.get("confidence"),
    }


async def _send_channel_error(channel: str, chat_id: str | None, error_message: str) -> None:
    """Enviar un mensaje de error al usuario en el canal correspondiente."""
    await _send_to_channel(channel, chat_id, error_message)


async def _send_to_channel(channel: str, chat_id: str | None, text: str) -> None:
    """Enviar texto al canal apropiado usando el channel manager."""
    from ai_platform.channels import DiscordChannel, TelegramChannel, WhatsAppChannel

    if not chat_id:
        return

    channel_map = {
        "telegram": lambda: TelegramChannel(),
        "discord": lambda: DiscordChannel(),
        "whatsapp": lambda: WhatsAppChannel(),
    }

    channel_instance_factory = channel_map.get(channel)
    if not channel_instance_factory:
        return

    try:
        channel_instance = channel_instance_factory()
        await channel_instance.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logging.getLogger(__name__).error(f"Error enviando al canal {channel}: {e}")


def _extract_response_text(module_result: Any) -> str:
    """Extraer texto legible del resultado del módulo."""
    # Keys que son metadatos, no respuestas al usuario
    _METADATA_KEYS = {
        "module", "status", "action", "error", "timestamp", "channel",
        "session_id", "confidence", "reasoning", "params", "needs_decomposition",
        "subtasks", "session_context", "memory_context", "kb_context",
        "result", "note", "data",
    }
    # Strings que típicamente son valores de metadata no válidos como respuesta
    _STATUS_STRINGS = {"success", "ok", "pending", "completed", "failed", "error", "ignored", "rejected", "handled"}

    if isinstance(module_result, dict):
        # Prioridad: response > message > text > result.nested > datos
        for key in ("response", "message", "text"):
            if key in module_result:
                val = module_result[key]
                if isinstance(val, str) and val.strip():
                    return val[:4096]
        # Si result es un dict, buscar dentro de él
        if "result" in module_result and isinstance(module_result["result"], dict):
            nested = module_result["result"]
            for key in ("response", "message", "text", "reply"):
                if key in nested:
                    val = nested[key]
                    if isinstance(val, str) and val.strip():
                        return val[:4096]
            # fallback: usar primer string dentro de result que no sea metadata
            for key in ("response", "message", "text", "reply"):
                if key in nested:
                    val = nested[key]
                    if isinstance(val, str) and val.strip() and val not in _STATUS_STRINGS:
                        return val[:4096]
        # Usar cualquier string dentro de result si nada más funciona
        if "result" in module_result and isinstance(module_result["result"], str):
            val = module_result["result"]
            if val.strip() and val not in _STATUS_STRINGS:
                return val[:4096]
        # Si hay cualquier campo con string, usar el primero (excluyendo metadata)
        for key, val in module_result.items():
            if isinstance(val, str) and val.strip():
                if key not in _STATUS_STRINGS and val not in _STATUS_STRINGS:
                    return val[:4096]
        if "error" in module_result:
            return str(module_result["error"])
    elif isinstance(module_result, str) and module_result.strip():
        if module_result not in _STATUS_STRINGS:
            return module_result[:4096]
    return ""
    return ""


async def _execute_module(
    module_name: str,
    action: str,
    params: dict[str, Any],
    tenant_id: str,
    user_id: str,
    channel: str,
    chat_id: str,
    message_text: str,
) -> dict[str, Any]:
    """Ejecutar el módulo seleccionado dinámicamente."""
    from ai_platform.orchestrator.modules import get_handler

    HandlerClass = get_handler(module_name)
    if HandlerClass is None:
        return {
            "module": module_name,
            "status": "failed",
            "error": f"Módulo {module_name} no tiene handler",
        }

    try:
        handler_instance = HandlerClass()
        execute_result = handler_instance.execute(
            {
                "module": module_name,
                "action": action,
                "params": {**params, "chat_id": chat_id, "channel": channel},
                "metadata": {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "channel": channel,
                    "message_text": message_text,
                },
            }
            )
        return execute_result

    except Exception as e:
        return {
            "module": module_name,
            "status": "failed",
            "error": str(e),
        }


def channel_update_channel(session_id: str, channel: str, chat_id: str, channel_user_id: str | None = None):
    """
    Actualizar el chat_id del mapeo de canal asociado a la sesión.

    Esto permite que la próxima vez que el usuario escriba por el mismo chat,
    se encuentre su mapeo correctamente.

    Parámetros:
        session_id: ID de la sesión de Odin
        channel: Canal ("telegram", "discord", "whatsapp")
        chat_id: Chat_id actual del usuario
        channel_user_id: ID del usuario en el canal (para filtrar el mapeo correcto)
    """
    from ai_platform.database import make_session

    if not chat_id:
        return

    with make_session() as db:
        if channel_user_id:
            db.execute(
                text("""
                    UPDATE channel_mappings
                    SET channel_chat_id = :chat_id
                    WHERE channel = :channel
                      AND channel_user_id = :channel_user_id
                """),
                {"chat_id": chat_id, "channel": channel, "channel_user_id": channel_user_id},
            )
        else:
            db.execute(
                text("""
                    UPDATE channel_mappings
                    SET channel_chat_id = :chat_id
                    WHERE channel = :channel
                      AND channel_user_id IS NOT NULL
                """),
                {"chat_id": chat_id, "channel": channel},
            )
        db.commit()


async def channel_get_tenant_id_for_channel_user(
    channel: str,
    channel_user_id: str,
) -> dict[str, str] | None:
    """
    Buscar el tenant_id para un usuario de un canal específico.

    Parámetros:
        channel: Canal ("telegram", "discord", "whatsapp")
        channel_user_id: ID del usuario en el canal

    Retorna:
        Dict con tenant_id y user_id (si existe), o None si no se encuentra
    """
    from ai_platform.database import make_session

    with make_session() as db:
        result = db.execute(
            text("""
                SELECT tenant_id, user_id
                FROM channel_mappings
                WHERE channel = :channel
                  AND channel_user_id = :channel_user_id
                LIMIT 1
            """),
            {
                "channel": channel,
                "channel_user_id": channel_user_id,
            },
        ).first()

        if result:
            return {
                "tenant_id": str(result[0]),
                "user_id": str(result[1]),
            }

        return None
