"""
Webhooks de Clerk y Stripe para sincronización de datos.

Clerk envía webhooks cuando:
- user.created → Nuevo usuario registrado
- user.updated → Usuario actualizado
- user.deleted → Usuario eliminado

Stripe envía webhooks cuando:
- customer.subscription.created → Nueva suscripción
- customer.subscription.updated → Plan cambiado
- customer.subscription.deleted → Cancelación
- invoice.payment_succeeded → Pago exitoso
- invoice.payment_failed → Pago fallido

Configuración:
1. En Clerk Dashboard → Webhooks → Add Endpoint
   URL: https://tu-dominio.com/api/v1/webhooks/clerk
2. En Stripe Dashboard → Developers → Webhooks → Add endpoint
   URL: https://tu-dominio.com/api/v1/webhooks/stripe

"""

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Request, status
from sqlalchemy import text

from ai_platform.database import session_factory
from ai_platform.models.db import Tenant, UsageEvent, User

router = APIRouter()


# ============================================================================
# Webhooks de Clerk
# ============================================================================


def verify_clerk_signature(payload: bytes, signature: str) -> bool:
    """
    Verificar la firma de un webhook de Clerk.

    Clerk firma cada webhook con HMAC-SHA256 usando tu secret key.
    """
    import os

    webhook_secret = os.environ.get("CLERK_WEBHOOK_SECRET", "")

    if not webhook_secret:
        return False  # En producción, la firma SIEMPRE debe verificarse

    timestamp = os.environ.get("CLERK_WEBHOOK_TIMESTAMP", "0")
    message = f"{timestamp}.{payload.decode('utf-8')}"
    expected_signature = hmac.new(webhook_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


async def handle_user_created(data: dict) -> dict:
    """
    Manejar evento user.created.

    Cuando un usuario se registra en Clerk:
    1. Crear un tenant automáticamente
    2. Crear el usuario en nuestra BD
    3. Asignar plan starter
    """
    user_id = data.get("id")
    email = data.get("email_addresses", [{}])[0].get("email_address", "")
    first_name = data.get("first_name", "")
    last_name = data.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip()

    session = session_factory()
    try:
        # Verificar si el usuario ya existe
        existing = session.query(User).filter_by(clerk_user_id=user_id).first()
        if existing:
            return {"status": "already_exists", "user_id": user_id}

        # Buscar o crear tenant
        tenant = session.query(Tenant).filter_by(clerk_user_id=user_id).first()
        if not tenant:
            slug = f"{first_name.lower()}-{last_name.lower()}-{user_id[:8]}"
            tenant = Tenant(
                name=f"{full_name}'s Company" if full_name else "New Company",
                slug=slug,
                plan="starter",
                clerk_user_id=user_id,
                billing_email=email,
            )
            session.add(tenant)
            session.flush()

        # Crear usuario
        user = User(tenant_id=tenant.id, clerk_user_id=user_id, email=email, name=full_name, role="admin")
        session.add(user)
        session.commit()

        return {"status": "created", "user_id": user_id, "tenant_id": str(tenant.id), "email": email}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


@router.post("/webhooks/clerk")
async def clerk_webhook(request: Request):
    """
    Endpoint de webhook de Clerk.

    Clerk envía eventos cuando ocurren cambios en usuarios.
    Usamos esto para sincronizar con nuestra BD.
    """
    signature = request.headers.get("Clerk-Signature")
    timestamp = request.headers.get("Clerk-Webhook-Timestamp")

    if signature and timestamp:
        payload = await request.body()
        if not verify_clerk_signature(payload, signature):
            return {"status": "error", "message": "Firma inválida"}, status.HTTP_401_UNAUTHORIZED

    event = json.loads(await request.body())
    event_type = event.get("type")
    data = event.get("data", {})

    if event_type == "user.created":
        return await handle_user_created(data)
    elif event_type == "user.updated" or event_type == "user.deleted":
        return {"status": "ignored", "event": event_type}

    return {"status": "ignored", "event": event_type}


# ============================================================================
# Webhooks de Stripe
# ============================================================================


def verify_stripe_signature(payload: bytes, signature: str) -> bool:
    """
    Verificar la firma de un webhook de Stripe.
    """
    import os

    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        return False  # En producción, la firma SIEMPRE debe verificarse

    parts = signature.split(",")
    timestamp = ""
    sig = ""
    for part in parts:
        if part.startswith("t="):
            timestamp = part[2:]
        elif part.startswith("v1="):
            sig = part[3:]

    if not sig:
        return False

    message = f"{timestamp}.{payload.decode('utf-8')}"
    expected = hmac.new(webhook_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected, sig)


async def handle_subscription_created(data: dict) -> dict:
    """
    Manejar nueva suscripción.

    Cuando un cliente se suscribe:
    1. Extraer tenant_id del metadata
    2. Actualizar plan en nuestra BD
    3. Registrar evento de uso
    """
    subscription_id = data.get("id")
    status = data.get("status")
    tenant_id = data.get("metadata", {}).get("tenant_id")

    if not tenant_id:
        return {"status": "error", "message": "No tenant_id in metadata"}

    price_id = data.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", "")
    plan = _extract_plan_from_price_id(price_id)

    session = session_factory()
    try:
        tenant = session.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return {"status": "error", "message": "Tenant not found"}

        tenant.plan = plan
        tenant.is_active = status == "active"
        session.commit()

        return {
            "status": "subscription_created",
            "tenant_id": tenant_id,
            "plan": plan,
            "subscription_id": subscription_id,
        }
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


async def handle_subscription_updated(data: dict) -> dict:
    """
    Manejar cambio de suscripción (upgrade/downgrade).
    """
    status = data.get("status")
    tenant_id = data.get("metadata", {}).get("tenant_id")

    if not tenant_id:
        return {"status": "error", "message": "No tenant_id in metadata"}

    price_id = data.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", "")
    plan = _extract_plan_from_price_id(price_id)

    session = session_factory()
    try:
        tenant = session.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return {"status": "error", "message": "Tenant not found"}

        old_plan = tenant.plan
        tenant.plan = plan
        tenant.is_active = status == "active"
        session.commit()

        return {"status": "subscription_updated", "tenant_id": tenant_id, "old_plan": old_plan, "new_plan": plan}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


async def handle_subscription_deleted(data: dict) -> dict:
    """
    Manejar cancelación de suscripción.
    """
    tenant_id = data.get("metadata", {}).get("tenant_id")

    if not tenant_id:
        return {"status": "error", "message": "No tenant_id in metadata"}

    session = session_factory()
    try:
        tenant = session.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return {"status": "error", "message": "Tenant not found"}

        tenant.plan = "free"
        tenant.is_active = True
        session.commit()

        return {"status": "subscription_deleted", "tenant_id": tenant_id, "new_plan": "free"}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


async def handle_payment_succeeded(data: dict) -> dict:
    """
    Manejar pago exitoso.
    """
    tenant_id = data.get("metadata", {}).get("tenant_id")
    amount_paid = data.get("amount_paid", 0)
    currency = data.get("currency", "usd")

    if not tenant_id:
        return {"status": "error", "message": "No tenant_id in metadata"}

    session = session_factory()
    try:
        usage = UsageEvent(
            tenant_id=tenant_id,
            module="billing",
            event_type="payment_succeeded",
            tokens_used=0,
            cost_usd=amount_paid / 100,
        )
        session.add(usage)
        session.commit()

        return {
            "status": "payment_succeeded",
            "tenant_id": tenant_id,
            "amount": amount_paid / 100,
            "currency": currency,
        }
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        session.close()


async def handle_payment_failed(data: dict) -> dict:
    """
    Manejar pago fallido.
    """
    tenant_id = data.get("metadata", {}).get("tenant_id")

    if not tenant_id:
        return {"status": "error", "message": "No tenant_id in metadata"}

    return {
        "status": "payment_failed",
        "tenant_id": tenant_id,
        "message": "Notificar al cliente para actualizar método de pago",
    }


def _extract_plan_from_price_id(price_id: str) -> str:
    """
    Extraer nombre del plan desde el price_id de Stripe.

    Los price_id siguen el formato: price_123_starter_monthly
    """
    if not price_id:
        return "starter"

    parts = price_id.split("_")
    if len(parts) >= 3:
        plan_name = parts[2]
        valid_plans = ["starter", "pro", "enterprise"]
        if plan_name in valid_plans:
            return plan_name

    return "starter"


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Endpoint de webhook de Stripe.

    Stripe envía eventos cuando ocurren cambios en suscripciones/pagos.
    Usamos esto para actualizar el plan del tenant en nuestra BD.
    """
    signature = request.headers.get("Stripe-Signature")

    if signature:
        payload = await request.body()
        if not verify_stripe_signature(payload, signature):
            return {"status": "error", "message": "Firma inválida"}, status.HTTP_401_UNAUTHORIZED

    event = json.loads(await request.body())
    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})

    if event_type == "customer.subscription.created":
        return await handle_subscription_created(data)
    elif event_type == "customer.subscription.updated":
        return await handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        return await handle_subscription_deleted(data)
    elif event_type == "invoice.payment_succeeded":
        return await handle_payment_succeeded(data)
    elif event_type == "invoice.payment_failed":
        return await handle_payment_failed(data)

    return {"status": "ignored", "event": event_type}


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

    payload = await request.body()
    channel = TelegramChannel()

    # Validar webhook
    validation = channel.validate_webhook(payload, dict(request.headers))
    if not validation.get("valid"):
        logger.warning(f"Telegram webhook no validado: {validation.get('reason')}")
        return {"status": "rejected", "reason": validation.get("reason")}

    import json

    update_data = json.loads(payload)

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
    validation = channel.validate_webhook(payload, dict(request.headers))
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

    Este método conecta el webhook del canal con el flujo de Ragnar:
    1. Buscar o crear mapeo de canal → usuario de plataforma
    2. Llamar a Ragnar.decide() para routing del módulo
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
    from ai_platform.models.channel_mapping import get_or_create_channel_mapping
    from ai_platform.orchestrator.ragnar import get_ragnar

    # Obtener instancias
    ragnar = get_ragnar()

    # Paso 1: Buscar mapeo de canal externo → usuario de plataforma
    with make_session() as db:
        mapping = get_or_create_channel_mapping(
            db=db,
            tenant_id=None,
            user_id=None,
            channel=channel,
            channel_user_id=user_id,
            channel_username=user_name,
            channel_chat_id=chat_id,
        )

    if not mapping:
        return {"status": "error", "message": "No se pudo crear mapeo de canal"}

    logger = logging.getLogger(__name__)

    tenant_id = str(mapping.tenant_id)
    user_id_platform = str(mapping.user_id)

    # Paso 2: Llamar a Ragnar para routing
    try:
        decision = await ragnar.decide(
            prompt=message_text,
            tenant_id=tenant_id,
            user_id=user_id_platform,
            session_id=None,
        )
    except Exception as e:
        logger.error(f"Error en Ragnar.decide(): {e}")
        return {"status": "error", "message": str(e)}

    session_id = decision.get("session_id")

    # Paso 3: Actualizar session_id en mapeo
    if session_id:
        channel_update_channel(session_id=session_id, channel=channel, chat_id=chat_id)

    return {
        "status": "success",
        "channel": channel,
        "module": decision["module"],
        "session_id": decision["session_id"],
        "action": decision["action"],
        "confidence": decision.get("confidence"),
    }


def channel_update_channel(session_id: str, channel: str, chat_id: str):
    """
    Actualizar el chat_id del mapeo de canal asociado a la sesión.

    Esto permite que la próxima vez que el usuario escriba por el mismo chat,
    se encuentre su mapeo correctamente.

    Parámetros:
        session_id: ID de la sesión de Ragnar
        channel: Canal ("telegram", "discord", "whatsapp")
        chat_id: Chat_id actual del usuario
    """
    from ai_platform.database import make_session

    if not chat_id:
        return

    with make_session() as db:
        # Actualizar el mapa del canal si ya existe
        from sqlalchemy import text

        db.execute(
            text("""
                UPDATE channel_mappings
                SET channel_chat_id = :chat_id
                WHERE channel = :channel
                  AND EXISTS (
                    SELECT 1 FROM sessions WHERE sessions.id = channel_mappings.channel_user_id
                  )
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
