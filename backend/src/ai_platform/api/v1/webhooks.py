"""
Webhooks de canales (Telegram, Discord, WhatsApp).

Endpoint único para enrutar mensajes entrantes desde canales de comunicación
al orquestador Odin, que decide qué módulo de negocio ejecutar.

"""

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter()


# ============================================================================
# Webhooks de Canales (Telegram, Discord, WhatsApp)
# ============================================================================


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    """
    Endpoint de webhook de Telegram.

    Recepción de mensajes entrantes desde Telegram Bot API.
    Soporta: texto, documentos, imágenes, audio, notas de voz, video,
             callback queries (botones inline).
    """
    from ai_platform.channels.telegram import TelegramChannel

    logger = logging.getLogger(__name__)

    payload_bytes = await request.body()
    if not payload_bytes:
        logger.warning("Telegram webhook: body vacío recibido")
        return {"status": "error", "reason": "empty_body"}
    try:
        update_data = json.loads(payload_bytes)
    except json.JSONDecodeError as e:
        logger.error(f"Telegram webhook: JSON inválido: {e}")
        return {"status": "error", "reason": "invalid_json"}
    channel = TelegramChannel()

    # Validar webhook
    validation = await channel.validate_webhook(update_data, dict(request.headers))
    if not validation.get("valid"):
        logger.warning(f"Telegram webhook no validado: {validation.get('reason')}")
        return {"status": "rejected", "reason": validation.get("reason")}

    # Extraer datos del mensaje (soporta message, edited_message, channel_post)
    message = (
        update_data.get("message")
        or update_data.get("edited_message")
        or update_data.get("channel_post")
    )

    # Manejar callback queries (clicks en botones inline)
    callback_query = update_data.get("callback_query")
    if callback_query:
        return await _handle_callback_query(
            channel=channel,
            callback_query=callback_query,
            request=request,
        )

    if not message:
        return {"status": "ignored", "reason": "sin_mensaje"}

    # Extraer con soporte de archivos adjuntos
    extracted = await channel.extract_message(update_data)

    user_id = extracted.get("user_id", "")
    user_name = extracted.get("user_name", "unknown")
    chat_id = extracted.get("chat_id", "")
    message_text = extracted.get("message_text", "")
    attachments = extracted.get("attachments", [])

    reply_to_message_id = message.get("reply_to_message", {}).get("message_id")

    # If there's a photo, download it and get a description via vision model
    if attachments:
        photos = [a for a in attachments if a.get("type") == "photo" and a.get("file_id")]
        photo_descriptions = []
        if photos:
            from ai_platform.orchestrator.llm_client import LLMClient

            llm_client = LLMClient()
            try:
                for photo in photos:
                    photo_bytes, _ = await channel.download_photo(photo["file_id"])
                    if photo_bytes:
                        desc = await llm_client.vision_chat(
                            "Describe esta imagen en español con detalle. Si es un gráfico, extrae los datos clave. Si es una escena, describe lo que se ve.",
                            photo_bytes,
                        )
                        text = desc.get("text", "") if isinstance(desc, dict) else str(desc)
                        if text and text.strip():
                            photo_descriptions.append(text)
            finally:
                try:
                    await llm_client.close()
                except Exception:
                    pass

        # Procesar archivos adjuntos (transcribir voz, descargar documentos, etc.)
        message_text, reply_to_message_id = await _process_tg_attachments(
            channel=channel,
            user_id=user_id,
            chat_id=chat_id,
            message_text=message_text,
            attachments=attachments,
            photo_descriptions=photo_descriptions,
            reply_to_message_id=reply_to_message_id,
        )

    logger.info(f"Mensaje entrante Telegram: user={user_id}, text={message_text[:100]}, files={len(attachments)}")

    # Responder inmediatamente a Telegram para evitar timeout (25s)
    # El procesamiento real se ejecuta en background
    asyncio.create_task(
        _process_channel_message(
            channel="telegram",
            user_id=user_id,
            user_name=user_name,
            chat_id=chat_id,
            message_text=message_text,
            reply_to_message_id=reply_to_message_id,
        )
    )
    return {"status": "ok", "message": "received"}


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

    # Responder inmediatamente a Meta para evitar timeout
    asyncio.create_task(
        _process_channel_message(
            channel="whatsapp",
            user_id=user_id,
            user_name=user_name,
            chat_id=chat_id,
            message_text=message_text,
        )
    )
    return {"status": "ok", "message": "received"}


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
    payload_bytes = await request.body()
    payload_bytes = payload_bytes.strip()

    try:
        import json
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        logger.warning("Discord webhook body no es JSON válido")
        return {"status": "rejected", "reason": "invalid_json"}

    channel = DiscordChannel()

    # Validar webhook de Discord (pasar dict, no bytes)
    validation = await channel.validate_webhook(payload, dict(request.headers))

    # Type 1: challenge de verificación — responder inmediatamente
    if validation.get("response"):
        return validation["response"]

    if not validation.get("valid"):
        logger.warning(f"Discord webhook no validado: {validation.get('reason')}")
        return {"status": "rejected", "reason": validation.get("reason")}

    # Extraer channel_id temprano para validación de permisos
    message = payload.get("message", {})
    data = payload.get("data", {})
    channel_id_raw = payload.get("channel_id", message.get("channel_id", ""))

    # Validar canal permitido
    allowed_channels = [
        cid.strip()
        for cid in os.environ.get("ALLOWED_DISCORD_CHANNELS", "").split(",")
        if cid.strip()
    ]
    if allowed_channels and str(channel_id_raw) not in allowed_channels:
        logger.warning(f"Ignorando interacción de canal no autorizado: {channel_id_raw}")
        return {"status": "ignored", "reason": "channel_not_allowed"}

    # Extraer usuario y mensaje según tipo de interacción
    user = payload.get("member", {}).get("user", payload.get("user", {}))

    user_id = str(user.get("id", ""))
    user_name = user.get("username", user.get("global_name", "unknown"))
    chat_id = str(channel_id_raw)

    # Obtener texto del mensaje/interacción
    if data.get("options"):
        message_text = data["options"][0].get("value", "") or data.get("content", "")
    else:
        message_text = payload.get("content", "") or data.get("content", "")

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


async def _process_tg_attachments(
    channel: Any,
    user_id: str,
    chat_id: str,
    message_text: str,
    attachments: list[dict],
    reply_to_message_id: int | None = None,
    photo_descriptions: list[str] | None = None,
) -> tuple[str, int | None]:
    """Procesar archivos adjuntos de Telegram de forma silenciosa.

    - Voice notes: se transcriben y la transcripción se convierte en message_text
    - Documents: se extrae el texto y se agrega al message_text
    - Photos: se describen con LLM vision y se agregan al message_text

    Retorna:
        (message_text_modificado, reply_to_message_id_actualizado)
    """
    if not attachments:
        return message_text, reply_to_message_id

    processed = await channel.process_attachments(attachments, chat_id, reply_to_message_id)
    if not processed:
        return message_text, reply_to_message_id

    voice_transcriptions = []
    document_texts = []
    caption_parts = []

    for p in processed:
        ptype = p.get("type")

        if ptype == "voice":
            transcription = p.get("transcription", "")
            if transcription and transcription != "[No se pudo transcribir el audio":
                voice_transcriptions.append(transcription)
            elif transcription:
                voice_transcriptions.append(f"[Nota de voz no transcrita: {transcription}]")
            # caption del voice se agrega como contexto adicional
            cap = p.get("caption", "")
            if cap:
                caption_parts.append(f"Caption del audio: {cap}")

        elif ptype == "document":
            extracted = p.get("extracted_text", "")
            if extracted and extracted.strip():
                file_name = p.get("file_name", "documento")
                file_ext = p.get("file_extension", "bin")
                caption = p.get("caption", "")
                doc_header = f"--- Contenido del documento '{file_name}' ({file_ext}) ---\n"
                document_texts.append(doc_header + extracted + "\n--- Fin del documento ---")
                if caption:
                    caption_parts.append(f"Caption del documento '{file_name}': {caption}")
            # Si no se pudo extraer texto, no mostramos nada al usuario
            # (el usuario no necesita saber si el documento es un PDF escaneado)

        elif ptype == "photo":
            cap = p.get("caption", "")
            if cap:
                caption_parts.append(f"Caption de la imagen: {cap}")

        elif ptype == "audio":
            title = p.get("title", "")
            if title:
                caption_parts.append(f"Audio: {title}")

        elif ptype in ("video", "video_note", "animation"):
            # Silenciosamente ignorados
            pass

    # Construir message_text final
    # 1. Transcripción de voz (si hay) → es el contenido principal del mensaje
    # 2. Texto extraído de documentos → se agrega como contexto
    # 3. Caption del usuario → se mantiene
    # 4. El original message_text → se mantiene como contexto

    final_parts = []

    if voice_transcriptions:
        for vt in voice_transcriptions:
            if vt:
                final_parts.append(vt)

    if photo_descriptions:
        for pd_text in photo_descriptions:
            if pd_text:
                final_parts.append(pd_text)

    if document_texts:
        for dt in document_texts:
            if dt:
                final_parts.append(dt)

    if caption_parts:
        for cp in caption_parts:
            if cp:
                final_parts.append(cp)

    if message_text and message_text.strip():
        final_parts.append(message_text)

    if final_parts:
        message_text = "\n\n".join(final_parts).strip()

    # Limpiar temp files
    for p in processed:
        temp_path = p.get("temp_path")
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    return message_text, reply_to_message_id


async def _process_channel_message(
    channel: str,
    user_id: str,
    user_name: str,
    chat_id: str,
    message_text: str,
    reply_to_message_id: int | None = None,
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

    # DEBUG LOG
    logger.info("=" * 60)
    logger.info(f"ODIN DECISION: module={module_name!r}, action={action!r}, confidence={decision.get('confidence')}")
    logger.info(f"ODIN DECISION: message={message_text[:150]!r}")
    logger.info(f"ODIN DECISION: channel={channel}, chat_id={chat_id}")
    logger.info("=" * 60)

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
        # Reacción 🧐 para indicar que se está procesando
        reaction_ok = await _send_reaction(channel, chat_id, reply_to_message_id, "\U0001fae0")

        # Typing indicator (envía una indicación al cliente, es solo signal)
        try:
            if channel == "telegram":
                from ai_platform.channels import TelegramChannel
                tg_typing = TelegramChannel()
                await tg_typing.send_chat_action(chat_id)
                await asyncio.sleep(0.3)
        except Exception:
            pass

        # Enviar mensaje de progreso inicial y animarlo
        progress_msg_id = None
        type_task = None
        stop_progress = asyncio.Event()
        progress_stages = [
            "\U0001f50d <b>Analizando solicitud...</b>",
            "\u231b <b>Procesando...</b>",
            "\U0001f4a1 <b>Generando respuesta...</b>",
            "\U0001f4c4 <b>Finalizando...</b>",
        ]

        if reply_to_message_id:
            # Primero enviamos el primer mensaje de progreso
            progress_resp = await _send_to_channel(
                channel, chat_id, progress_stages[0], reply_to_message_id=reply_to_message_id
            )
            if progress_resp and progress_resp.get("result"):
                progress_msg_id = progress_resp["result"].get("message_id")

        if progress_msg_id:
            type_task = asyncio.create_task(
                _progress_pulsing(
                    channel, chat_id, progress_msg_id, stop_progress, progress_stages
                )
            )

        module_result = await odin_inst.execute(
            decision=decision,
            tenant_id=tenant_id,
            task_id=f"tg-{chat_id}-{reply_to_message_id}",
        )

        stop_progress.set()
        if type_task:
            type_task.cancel()
            try:
                await type_task
            except asyncio.CancelledError:
                pass

        # Reacción ✅ al terminar
        if reaction_ok:
            try:
                await _send_reaction(channel, chat_id, reply_to_message_id, "\u2705")
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Error ejecutando módulo {module_name}: {e}", exc_info=True)
        # Reacción ❌ de error
        if reaction_ok:
            try:
                await _send_reaction(channel, chat_id, reply_to_message_id, "\u274c")
            except Exception:
                pass
        stop_progress.set()
        if type_task:
            type_task.cancel()
        await _send_channel_error(channel, chat_id, "Error procesando tu solicitud")
        return {
            "status": "error",
            "message": f"Error ejecutando módulo {module_name}: {e!s}",
            "module": module_name,
        }

    # Actualizar module_name si Odin redirigió (ej: uncategorized → ai-connect)
    updated_module = decision["module"]
    if updated_module != module_name:
        logger.info(f"ODIN redirect: {module_name!r} → {updated_module!r}")
        module_name = updated_module

    logger.info(f"MODULE_RESULT keys: {list(module_result.keys())}")

    # Paso 5: Enviar respuesta de vuelta al canal
    response_text = _extract_response_text(module_result)
    has_response = bool(response_text)

    if has_response:
        # Reemplazar el mensaje de progreso por la respuesta real
        if progress_msg_id:
            try:
                import html
                response_html = html.escape(response_text)
                # Replace * with ** for markdown-bold
                response_html = response_html.replace("\\n", " ")

                from ai_platform.channels import TelegramChannel
                tg_resp = TelegramChannel()
                edit_res = await tg_resp.edit_message_text(chat_id, progress_msg_id, response_text, parse_mode="HTML")
                if not isinstance(edit_res, dict) or not edit_res.get("ok"):
                    logger.warning(f"Edit progress msg returned {edit_res}, fallback sending new message")
                    await _send_to_channel(channel, chat_id, response_text, reply_to_message_id=reply_to_message_id)
            except Exception as e:
                logger.warning(f"Error editing progress msg: {e}, sending as new message")
                await _send_to_channel(channel, chat_id, response_text, reply_to_message_id=reply_to_message_id)
        else:
            # Enviar como mensaje nuevo
            await _send_to_channel(channel, chat_id, response_text, reply_to_message_id=reply_to_message_id)
    else:
        # Sin texto de respuesta → eliminar el mensaje de progreso
        if progress_msg_id:
            try:
                from ai_platform.channels import TelegramChannel
                tg_del = TelegramChannel()
                await tg_del.delete_message(chat_id, progress_msg_id)
            except Exception:
                pass

    return {
        "status": "success",
        "channel": channel,
        "module": module_name,
        "session_id": session_id,
        "action": action,
        "confidence": decision.get("confidence"),
    }


async def _send_reaction(channel: str, chat_id: str | None, message_id: int | None, emoji: str) -> dict | None:
    """Enviar reacción emoji a un mensaje (Telegram reaction)."""
    if not chat_id or not message_id:
        return None

    if channel != "telegram":
        return None

    try:
        from ai_platform.channels.telegram import TelegramChannel

        tg = TelegramChannel()
        return await tg.set_reaction(chat_id, message_id, emoji)
    except Exception:
        return None


async def _progress_pulsing(
    channel: str,
    chat_id: str,
    message_id: int,
    stop: asyncio.Event,
    stages: list[str],
) -> None:
    """Background task que cicla mensajes de progreso cada 5 segundos."""
    idx = 0
    while not stop.is_set():
        try:
            from ai_platform.channels.telegram import TelegramChannel

            tg = TelegramChannel()
            await tg.edit_message_text(chat_id, message_id, stages[idx % len(stages)])
            idx += 1
            stop.wait(5)
        except asyncio.CancelledError:
            break
        except Exception:
            break


async def _send_channel_error(channel: str, chat_id: str | None, error_message: str) -> None:
    """Enviar un mensaje de error al usuario en el canal correspondiente."""
    await _send_to_channel(channel, chat_id, error_message)


async def _send_to_channel(channel: str, chat_id: str | None, text: str, reply_to_message_id: int | None = None) -> None:
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
        await channel_instance.send_message(chat_id=chat_id, text=text, reply_to_message_id=reply_to_message_id)
    except Exception as e:
        logging.getLogger(__name__).error(f"Error enviando al canal {channel}: {e}")


def _extract_response_text(module_result: Any) -> str:
    """Extraer texto legible del resultado del módulo."""
    # Keys que son metadatos, no respuestas al usuario
    _METADATA_KEYS = {
        "module", "status", "action", "error", "timestamp", "channel",
        "session_id", "confidence", "reasoning", "params", "needs_decomposition",
        "subtasks", "session_context", "memory_context", "kb_context",
        "note", "data",
    }
    # Strings que típicamente son valores de metadata no válidos como respuesta
    _STATUS_STRINGS = {"success", "ok", "pending", "completed", "failed", "error", "ignored", "rejected", "handled"}

    if isinstance(module_result, dict):
        # Prioridad 1: response > message > text > reply (campos directos)
        for key in ("response", "message", "text", "reply"):
            if key in module_result:
                val = module_result[key]
                if isinstance(val, str) and val.strip():
                    return val[:4096]
                elif isinstance(val, dict):
                    # response puede ser un dict {response: "..."}
                    for inner_key in ("response", "message", "text", "reply", "content"):
                        if inner_key in val:
                            inner_val = val[inner_key]
                            if isinstance(inner_val, str) and inner_val.strip():
                                return inner_val[:4096]
        # Prioridad 2: result como string (ej: ai-documents._default)
        if "result" in module_result:
            val = module_result["result"]
            if isinstance(val, str) and val.strip() and val not in _STATUS_STRINGS:
                return val[:4096]
            elif isinstance(val, dict):
                # result como dict: buscar response/message/text dentro
                for key in ("response", "message", "text", "reply", "content"):
                    if key in val:
                        inner_val = val[key]
                        if isinstance(inner_val, str) and inner_val.strip():
                            return inner_val[:4096]
        # Prioridad 3: cualquier campo con string que no sea metadata
        for key, val in module_result.items():
            if key in _METADATA_KEYS:
                continue
            if isinstance(val, str) and val.strip() and val not in _STATUS_STRINGS:
                return val[:4096]
            # Si es dict, buscar contenido dentro
            elif isinstance(val, dict):
                for inner_key in ("response", "message", "text", "reply", "content", "result"):
                    if inner_key in val:
                        inner_val = val[inner_key]
                        if isinstance(inner_val, str) and inner_val.strip() and inner_val not in _STATUS_STRINGS:
                            return inner_val[:4096]
        # Prioridad 4: error como respuesta final
        if "error" in module_result:
            return str(module_result["error"])
    elif isinstance(module_result, str) and module_result.strip():
        if module_result not in _STATUS_STRINGS:
            return module_result[:4096]
    return ""


async def _try_ai_connect_fallback(
    message_text: str,
    chat_id: str,
    channel: str,
    tenant_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Intentar procesar el mensaje con ai-connect cuando ningún otro módulo funciona."""
    from ai_platform.orchestrator.modules import get_handler

    handler_cls = get_handler("ai-connect")
    if handler_cls is None:
        logger.warning("ai-connect no disponible para fallback")
        return {
            "status": "failed",
            "error": "No se pudo procesar el mensaje: ningún módulo disponible",
        }

    try:
        handler = handler_cls()
        payload = {
            "module": "ai-connect",
            "action": "send_message",
            "params": {"chat_id": chat_id, "channel": channel},
            "metadata": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "channel": channel,
                "message_text": message_text,
            },
        }
        if asyncio.iscoroutinefunction(handler.execute):
            return await handler.execute(payload)
        else:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, handler.execute, payload)
    except Exception as e:
        logger.error(f"ai-connect fallback failed: {e}", exc_info=True)
        return {
            "status": "failed",
            "error": str(e),
        }


async def _execute_module(
    module_name: str,
    action: str,
    params: dict[str, Any],
    tenant_id: str,
    user_id: str,
    channel: str,
    chat_id: str,
    message_text: str,
    reply_to_message_id: int | None = None,
) -> dict[str, Any]:
    """Ejecutar el módulo seleccionado dinámicamente."""
    from ai_platform.orchestrator.modules import get_handler

    logger = logging.getLogger(__name__)

    # Fallback: uncategorized → ai-connect (módulo general de comunicación)
    if module_name == "uncategorized":
        logger.info(f"Module uncategorized, redirecting to ai-connect")
        module_name = "ai-connect"

    HandlerClass = get_handler(module_name)
    if HandlerClass is None:
        return {
            "module": module_name,
            "status": "failed",
            "error": f"Módulo {module_name} no tiene handler",
        }

    try:
        handler_instance = HandlerClass()
        payload = {
            "module": module_name,
            "action": action,
            "params": {**params, "chat_id": chat_id, "channel": channel},
            "metadata": {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "channel": channel,
                "message_text": message_text,
                "reply_to_message_id": reply_to_message_id,
            },
        }
        if asyncio.iscoroutinefunction(handler_instance.execute):
            execute_result = await handler_instance.execute(payload)
        else:
            loop = asyncio.get_running_loop()
            execute_result = await loop.run_in_executor(None, handler_instance.execute, payload)

        # Fallback: si la acción no es válida, verificar que el resultado tenga respuesta real
        if (
            isinstance(execute_result, dict)
            and execute_result.get("status") == "failed"
            and "no encontrada" in execute_result.get("error", "")
        ):
            logger.warning(f"Action inválida en {module_name}, reintentando con 'default'")
            default_payload = {
                "module": module_name,
                "action": "default",
                "params": {**params, "chat_id": chat_id, "channel": channel},
                "metadata": {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "channel": channel,
                    "message_text": message_text,
                    "reply_to_message_id": reply_to_message_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "chat_id": chat_id,
                },
            }
            if asyncio.iscoroutinefunction(handler_instance.execute):
                execute_result = await handler_instance.execute(default_payload)
            else:
                loop = asyncio.get_running_loop()
                execute_result = await loop.run_in_executor(None, handler_instance.execute, default_payload)
            # Si el default solo devolvió lista de acciones sin respuesta real, redirigir a ai-connect
            if "available_actions" in execute_result:
                logger.warning(f"Action default en {module_name} no devolvió respuesta, redirigiendo a ai-connect")
                execute_result = await _try_ai_connect_fallback(
                    message_text=message_text,
                    chat_id=chat_id,
                    channel=channel,
                    tenant_id=tenant_id,
                    user_id=user_id_platform,
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


# ============================================================================
# Callback Query Handler (Telegram inline keyboard buttons)
# ============================================================================


async def _handle_callback_query(
    channel: "TelegramChannel",
    callback_query: dict,
    request: Request,
) -> dict[str, Any]:
    """Manejar clicks en botones inline del webhook de Telegram."""
    from ai_platform.channels.telegram import (
        _ACTION_MAP,
        _FORMAT_MIME_MAP,
        TelegramChannel,
    )
    from ai_platform.database import make_session
    from ai_platform.models.channel_mapping import get_channel_user_info
    from ai_platform.orchestrator.odin import get_odin

    logger = logging.getLogger(__name__)

    callback_id = callback_query.get("id", "")
    callback_data = callback_query.get("data", "")
    from_data = callback_query.get("from", {})
    message_data = callback_query.get("message") or {}
    chat_data = message_data.get("chat", {})
    message_id = message_data.get("message_id")

    user_id = str(from_data.get("id", ""))
    chat_id = str(chat_data.get("id", ""))

    logger.info(f"Callback query: user={user_id}, chat={chat_id}, data={callback_data!r}")

    # Responder al callback para eliminar spinner del botón
    await channel.send_answer(callback_id, text="", show_alert=False)

    # Validar que tenga data
    if not callback_data:
        return {"status": "ignored", "reason": "no_callback_data"}

    # Responder para eliminar spinner del botón (Telegram requiere respuesta)
    # Ahora procesamos el callback
    if callback_data.startswith("format:"):
        # Selección de formato de documento
        format_choice = callback_data.split(":", 1)[1]

        # Resolver tenant_id
        with make_session() as db:
            mapping = db.execute(
                text("""
                    SELECT id, tenant_id, user_id FROM channel_mappings
                    WHERE channel = 'telegram' AND channel_user_id = :uid
                    LIMIT 1
                """),
                {"uid": user_id},
            ).first()

        if not mapping:
            await channel.send_answer(callback_id, text="No se encontró tu perfil. Escribe /start", show_alert=True)
            return {"status": "ignored", "reason": "no_mapping"}

        db.execute(
            text("""
                UPDATE channel_mappings
                SET channel_chat_id = :chat_id
                WHERE channel = 'telegram' AND channel_user_id = :uid
            """),
            {"chat_id": chat_id, "uid": user_id},
        )
        db.commit()

        if mapping.tenant_id:
            tenant_id = str(mapping.tenant_id)
        else:
            # Crear/obtener tenant default
            default_tenant_slug = "telegram-default"
            default_tenant = db.execute(
                text("SELECT id FROM tenants WHERE slug = :slug LIMIT 1"),
                {"slug": default_tenant_slug},
            ).first()

            if default_tenant:
                tenant_id = str(default_tenant.id)
            else:
                from uuid import uuid4
                default_tenant_id = uuid4()
                tenant_id = str(default_tenant_id)
                db.execute(
                    text("""
                        INSERT INTO tenants (id, name, slug, plan, is_active, created_at)
                        VALUES (:id, 'NeuralCrew Labs', :slug, 'starter', true, NOW())
                    """),
                    {"id": default_tenant_id, "slug": default_tenant_slug},
                )
                db.commit()

        # Obtener mensajes previos como contexto para generación
        previous_messages = _get_user_recent_messages(chat_id, user_id, db)

        # Ejecutar el módulo de documentos con el formato seleccionado
        action = _ACTION_MAP.get(format_choice, "render_all")
        params = {
            "format": format_choice,
        }

        # Usar mensajes anteriores como base para el contenido del documento
        if previous_messages:
            params["reference_messages"] = previous_messages

        logger.info(f"Callback format choice: {format_choice} -> {action}")

        # Enviar typing indicator y mensaje de progreso
        typing_ok = await channel.send_chat_action(chat_id)

        progress_msg_id = None
        progress_task = None
        stop_progress = asyncio.Event()

        try:
            if typing_ok:
                progress_task = asyncio.create_task(
                    _progress_watcher(channel, chat_id, message_id or 0, stop_progress)
                )

            module_result = await _execute_module(
                module_name="ai-documents",
                action=action,
                params=params,
                tenant_id=tenant_id,
                user_id=str(mapping.user_id) if mapping.user_id else user_id,
                channel="telegram",
                chat_id=chat_id,
                message_text=f"Documento generado desde callback, formato: {format_choice}",
                reply_to_message_id=message_id,
            )

            # Detener progress
            stop_progress.set()
            if progress_task:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass

            # Actualizar progreso a "listo"
            if progress_msg_id is not None:
                await channel.edit_message_text(
                    chat_id, progress_msg_id,
                    "\u2705 <b>\u00a1Listo!</b> Generando archivos..."
                )

            # Enviar archivo(s) generado(s)
            return await _send_document_result(
                channel=channel,
                module_result=module_result,
                chat_id=chat_id,
                original_message_id=message_id,
                reply_to_message_id=message_id,
            )

        except Exception as e:
            logger.error(f"Error executando documento desde callback: {e}", exc_info=True)
            stop_progress.set()
            if progress_task:
                progress_task.cancel()
            return {
                "status": "error",
                "message": f"Error generando documento: {e}",
            }

    elif callback_data.startswith("regenerate:"):
        # Regenerar último documento
        logger.info(f"Regenerate request from user={user_id}")
        await channel.send_answer(
            callback_id, text="Regenerando...",
            show_alert=False,
        )
        # TODO: Regenerar último documento guardado
        return {"status": "ignored", "reason": "regen_not_implemented"}

    elif callback_data.startswith("menu:"):
        logger.info(f"Menu callback from user={user_id}")
        await channel.send_answer(
            callback_id, text="",
            show_alert=False,
        )
        return {"status": "ignored", "reason": "menu_callback"}

    elif callback_data == "ask_changes":
        logger.info(f"Ask changes callback from user={user_id}")
        await channel.send_answer(
            callback_id, text="Escribe lo que quieres cambiar",
            show_alert=True,
        )
        return {"status": "ignored", "reason": "ask_changes"}

    return {"status": "processed"}


def _get_user_recent_messages(chat_id: str, user_id: str, db) -> list[str]:
    """Obtener los últimos mensajes del usuario para usar como contexto de documento."""
    recent = db.execute(
        text("""
            SELECT content FROM messages
            WHERE channel = 'telegram'
              AND (SELECT channel_user_id FROM channel_mappings
                   WHERE id = channel_mappings.channel_user_msg_mapping_id) = :uid
            ORDER BY created_at DESC
            LIMIT 10
        """),
        {"uid": user_id},
    ).fetchall()

    if recent:
        return [row[0] for row in recent if row[0]][:5]  # Top 5 messages
    return []


# ============================================================================
# Progress & Document sending helpers
# ============================================================================


async def _progress_watcher(
    channel: "TelegramChannel",
    chat_id: str,
    original_msg_id: int,
    stop: asyncio.Event,
) -> None:
    """Background task que actualiza el mensaje de progreso cada 3 segundos."""
    stages = [
        "\U0001f50d <b>Analizando solicitud...</b>",
        "\u231b <b>Generando documento...</b>",
        "\U0001f3a8 <b>Aplicando diseño profesional...</b>",
        "\U0001f4c4 <b>Finalizando formato...</b>",
    ]
    idx = 0
    while not stop.is_set():
        try:
            await channel.edit_message_text(
                chat_id, original_msg_id, stages[idx % len(stages)]
            )
            idx += 1
            stop.wait(3)  # Sleep for 3s, but can break early
        except Exception:
            break


async def _send_document_result(
    channel: "TelegramChannel",
    module_result: dict[str, Any],
    chat_id: str,
    original_message_id: int | None = None,
    reply_to_message_id: int | None = None,
) -> dict[str, Any]:
    """Enviar los archivos generados por ai-documents al usuario."""
    from ai_platform.channels.telegram import _FORMAT_MIME_MAP

    status = module_result.get("status", "unknown")

    if status == "success":
        formats = module_result.get("formats", {})
        formats_to_send = list(formats.keys()) if formats else ["pdf"]

        # Intentar enviar el formato principal primero
        main_format = formats_to_send[0] if formats_to_send else "pdf"
        main_format_bytes = module_result.get(main_format)

        if main_format_bytes:
            mime_type = _FORMAT_MIME_MAP.get(main_format, "application/octet-stream")
            filename = f"documento.{main_format}"

            # Verificar si es PDF (formato principal)
            if main_format == "pdf":
                resp = await channel.send_document_bytes(
                    chat_id=chat_id,
                    file_bytes=main_format_bytes,
                    filename=filename,
                    mime_type="application/pdf",
                    caption=f"\u2705 <b>Documento generado exitosamente</b>\n\nFormato: {main_format.upper()}",
                    reply_to_message_id=reply_to_message_id,
                )
                if resp and resp.get("ok"):
                    msg_id = resp["result"].get("message_id")
                    await _send_action_keyboard(channel, chat_id, msg_id)
                    return resp

        # Si no se pudo enviar el principal, intentar con el primer formato disponible
        for fmt in formats_to_send:
            file_bytes = module_result.get(fmt)
            if file_bytes:
                mime_type = _FORMAT_MIME_MAP.get(fmt, "application/octet-stream")
                if mime_type.startswith("image/"):
                    # Enviar como foto en lugar de documento
                    caption = f"\u2705 <b>Imagen generada ({fmt.upper()})</b>"
                    resp = await channel.send_photo(
                        chat_id=chat_id,
                        file_bytes=file_bytes,
                        caption=caption,
                        reply_to_message_id=reply_to_message_id,
                    )
                else:
                    resp = await channel.send_document_bytes(
                        chat_id=chat_id,
                        file_bytes=file_bytes,
                        filename=f"documento.{fmt}",
                        mime_type=mime_type,
                        caption=f"\u2705 <b>Documento generado ({fmt.upper()})</b>",
                        reply_to_message_id=reply_to_message_id,
                    )

                if resp and resp.get("ok"):
                    msg_id = resp["result"].get("message_id")
                    await _send_action_keyboard(channel, chat_id, msg_id)
                    return resp

        return {
            "status": "partial",
            "message": "Documento procesado pero hubo error al enviar al usuario.",
            "module": "ai-documents",
        }

    elif status == "failed" or "error" in module_result:
        error_msg = module_result.get("error", "Error desconocido")
        await channel.send_message(
            chat_id=chat_id,
            text=f"\u274c <b>Error al generar documento:</b>\n\n{error_msg}",
            reply_to_message_id=reply_to_message_id,
        )
        return {"status": "error", "message": error_msg}

    return {"status": "unknown"}


async def _send_action_keyboard(channel: "TelegramChannel", chat_id: str, message_id: int) -> None:
    """Enviar botones de acción debajo del documento."""
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "\U0001f504 Regenerar", "callback_data": "regenerate:doc"},
                {"text": "\U0001f4ac Pedir cambios", "callback_data": "ask_changes"},
            ],
            [
                {"text": "\U0001f4ca Otro formato", "callback_data": "format:all"},
                {"text": "\U0001f3e0 Menú", "callback_data": "menu:main"},
            ],
        ],
    }
    await channel.send_message(
        chat_id=chat_id,
        text="\u2705 \u00a1Documento generado con \u00e9xito!",
        reply_markup=keyboard,
        reply_to_message_id=message_id,
    )


def _build_format_selection_keyboard() -> dict:
    """Construir el teclado de selección de formato de documento."""
    return _FORMAT_KEYBOARD.copy()


async def _send_format_selection(
    channel: "TelegramChannel",
    chat_id: str,
    reply_to_message_id: int | None = None,
) -> dict[str, Any]:
    """Enviar mensaje con botones de selección de formato de documento."""
    keyboard = _build_format_selection_keyboard()
    response = await channel.send_message(
        chat_id=chat_id,
        text=(
            "\U0001f4c4 <b>Generar Documento</b>\n\n"
            "He detectado que quieres generar un documento. "
            "Elige el formato:"
        ),
        reply_markup=keyboard,
        reply_to_message_id=reply_to_message_id,
    )
    return response
