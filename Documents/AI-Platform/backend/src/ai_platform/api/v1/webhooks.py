"""
Webhooks de Clerk, Stripe y canales externos (Telegram, Discord, WhatsApp).

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

Canales externos envían webhooks cuando:
- /webhooks/telegram → Mensajes entrantes de Telegram
- /webhooks/discord → Mensajes entrantes de Discord
- /webhooks/whatsapp → Mensajes entrantes de WhatsApp

Configuración:
1. En Clerk Dashboard → Webhooks → Add Endpoint
   URL: https://tu-dominio.com/api/v1/webhooks/clerk
2. En Stripe Dashboard → Developers → Webhooks → Add endpoint
   URL: https://tu-dominio.com/api/v1/webhooks/stripe
3. En Telegram → @BotFather → /setwebhook
   URL: https://tu-dominio.com/api/v1/webhooks/telegram
4. En Discord → Developer Portal → Bot → Enable Message Content Intent
   URL: https://tu-dominio.com/api/v1/webhooks/discord
5. En Meta → WhatsApp → Webhook → Add Endpoint
   URL: https://tu-dominio.com/api/v1/webhooks/whatsapp

"""

import logging
from fastapi import APIRouter, Request, HTTPException, status
import hmac
import hashlib
import json
from typing import Dict, Any
from datetime import datetime, timezone

from ai_platform.database import session_factory
from ai_platform.models.db import Tenant, User, UsageEvent
from ai_platform.models.channel_mapping import get_channel_user_info

logger = logging.getLogger(__name__)

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
    WEBHOOK_SECRET = os.environ.get("CLERK_WEBHOOK_SECRET", "")
    
    if not WEBHOOK_SECRET:
        return True  # En desarrollo, no verificar firma
    
    timestamp = os.environ.get("CLERK_WEBHOOK_TIMESTAMP", "0")
    message = f"{timestamp}.{payload.decode('utf-8')}"
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    
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
                billing_email=email
            )
            session.add(tenant)
            session.flush()
        
        # Crear usuario
        user = User(
            tenant_id=tenant.id,
            clerk_user_id=user_id,
            email=email,
            name=full_name,
            role="admin"
        )
        session.add(user)
        session.commit()
        
        return {
            "status": "created",
            "user_id": user_id,
            "tenant_id": str(tenant.id),
            "email": email
        }
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
    elif event_type == "user.updated":
        return {"status": "ignored", "event": event_type}
    elif event_type == "user.deleted":
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
    WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    
    if not WEBHOOK_SECRET:
        return True  # En desarrollo, no verificar firma
    
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
    expected = hmac.new(
        WEBHOOK_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    
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
        return {"status": "error", "message": "No se encontró tenant_id en los metadatos"}
    
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
            "subscription_id": subscription_id
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
    subscription_id = data.get("id")
    status = data.get("status")
    tenant_id = data.get("metadata", {}).get("tenant_id")
    
    if not tenant_id:
        return {"status": "error", "message": "No se encontró tenant_id en los metadatos"}
    
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
        
        return {
            "status": "subscription_updated",
            "tenant_id": tenant_id,
            "old_plan": old_plan,
            "new_plan": plan
        }
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
        return {"status": "error", "message": "No se encontró tenant_id en los metadatos"}
    
    session = session_factory()
    try:
        tenant = session.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            return {"status": "error", "message": "Tenant not found"}
        
        tenant.plan = "free"
        tenant.is_active = True
        session.commit()
        
        return {
            "status": "subscription_deleted",
            "tenant_id": tenant_id,
            "new_plan": "free"
        }
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
        return {"status": "error", "message": "No se encontró tenant_id en los metadatos"}
    
    session = session_factory()
    try:
        usage = UsageEvent(
            tenant_id=tenant_id,
            module="billing",
            event_type="payment_succeeded",
            tokens_used=0,
            cost_usd=amount_paid / 100
        )
        session.add(usage)
        session.commit()
        
        return {
            "status": "payment_succeeded",
            "tenant_id": tenant_id,
            "amount": amount_paid / 100,
            "currency": currency
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
        return {"status": "error", "message": "No se encontró tenant_id en los metadatos"}
    
    return {
        "status": "payment_failed",
        "tenant_id": tenant_id,
        "message": "Notificar al cliente para actualizar método de pago"
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
# Webhooks de Canales Externos (Telegram, Discord, WhatsApp)
# ============================================================================

# Instancias de canales (se crean bajo demanda para evitar imports circulares)
_channel_instances: Dict[str, Any] = {}


def _get_channel(channel: str):
    """
    Obtener o crear la instancia del canal solicitado.

    Parámetros:
        channel: Nombre del canal ("telegram", "discord", "whatsapp")

    Retorna:
        Instancia del handler del canal

    Raises:
        ValueError: Si el canal no está configurado
    """
    if channel in _channel_instances:
        return _channel_instances[channel]

    if channel == "telegram":
        from ai_platform.channels.telegram import TelegramChannel
        _channel_instances[channel] = TelegramChannel()
        return _channel_instances[channel]
    elif channel == "discord":
        from ai_platform.channels.discord import DiscordChannel
        _channel_instances[channel] = DiscordChannel()
        return _channel_instances[channel]
    elif channel == "whatsapp":
        from ai_platform.channels.whatsapp_channel import WhatsAppChannel
        _channel_instances[channel] = WhatsAppChannel()
        return _channel_instances[channel]
    else:
        raise ValueError(f"Canal no soportado: {channel}")


def _extract_channel_user_id(payload: dict, channel: str) -> tuple:
    """
    Extraer el channel_user_id del payload de un canal externo.

    Cada canal tiene una estructura diferente para identificar al usuario.

    Parámetros:
        payload: Payload crudo del webhook
        channel: Nombre del canal ("telegram", "discord", "whatsapp")

    Retorna:
        Tupla (channel_user_id: str, channel_chat_id: str)
    """
    if channel == "telegram":
        message = payload.get("message") or payload.get("edited_message") or payload.get("channel_post")
        if message:
            user_info = message.get("from", {})
            chat_info = message.get("chat", {})
            user_id = str(user_info.get("id", ""))
            chat_id = str(chat_info.get("id", ""))
            return user_id, chat_id

    elif channel == "discord":
        # Slash command
        if payload.get("type") == 2:
            user_info = payload.get("member", {}).get("user", {})
            user_id = str(user_info.get("id", ""))
            chat_id = str(payload.get("channel_id", ""))
            return user_id, chat_id
        # Normal message
        author = payload.get("author", {})
        user_id = str(author.get("id", ""))
        chat_id = str(payload.get("channel_id", ""))
        return user_id, chat_id

    elif channel == "whatsapp":
        entries = payload.get("entry", [])
        if entries:
            entry = entries[0]
            changes = entry.get("changes", [])
            if changes:
                change = changes[0]
                value = change.get("value", {})
                messages = value.get("messages", [])
                if messages:
                    msg = messages[0]
                    user_id = msg.get("from", "")
                    # El chat_id en WhatsApp es el mismo que el from
                    chat_id = user_id
                    return user_id, chat_id

    return "", ""


def _resolve_tenant_id(channel: str, payload: dict) -> str:
    """
    Resolver el tenant_id para un mensaje de canal externo.

    Busca en channel_mappings por channel_user_id para encontrar
    el tenant_id asociado. Si no se encuentra, retorna cadena vacía.

    Parámetros:
        channel: Nombre del canal
        payload: Payload crudo del webhook

    Retorna:
        ID del tenant como string, o cadena vacía si no se encuentra
    """
    channel_user_id, _ = _extract_channel_user_id(payload, channel)
    if not channel_user_id:
        return ""

    mapping = get_channel_user_info(channel, channel_user_id)
    if mapping:
        return str(mapping.tenant_id)

    logger.info(f"No se encontró mapeo de canal para channel={channel}, channel_user_id={channel_user_id}")
    return ""


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request):
    """
    Endpoint de webhook de Telegram.

    Telegram envía un POST a este endpoint cuando el bot recibe un mensaje.
    El payload contiene el update completo con el mensaje del usuario.

    Flujo:
    1. Validar que el update viene de Telegram (con secret token si configurado)
    2. Extraer user_id, message_text, chat_id
    3. Resolver tenant_id desde channel_mappings
    4. Llamar a Ragnar.decide() para routing
    5. Ejecutar el módulo seleccionado
    6. Enviar respuesta al usuario en Telegram
    7. Guardar en la tabla messages

    Configuración:
    - TELEGRAM_BOT_TOKEN: Token del bot desde @BotFather
    - URL: https://tu-dominio.com/api/v1/webhooks/telegram
    """
    payload = await request.json()
    headers = dict(request.headers)

    try:
        channel = _get_channel("telegram")

        # Validar webhook con headers (para secret token)
        validation = await channel.validate_webhook(payload, headers)
        if not validation.get("valid"):
            logger.warning(f"Webhook de Telegram no válido: {validation.get('reason')}")
            return {"status": "error", "message": f"Webhook no validado: {validation.get('reason')}"}

        # Resolver tenant_id desde channel_mappings
        tenant_id = _resolve_tenant_id("telegram", payload)

        result = await channel.handle_webhook(
            raw_payload=payload,
            tenant_id=tenant_id,
        )

        return result

    except Exception as e:
        logger.error(f"Error en webhook de Telegram: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/webhooks/discord")
async def discord_webhook(request: Request):
    """
    Endpoint de webhook de Discord.

    Discord envía eventos a este endpoint cuando el bot recibe un mensaje.
    Soporta mensajes normales y slash commands.

    Flujo:
    1. Validar challenge GET o evento POST
    2. Validar que el evento viene de Discord (token configurado, estructura válida)
    3. Extraer user_id, message_text, channel_id
    4. Resolver tenant_id desde channel_mappings
    5. Llamar a Ragnar.decide() para routing
    6. Ejecutar el módulo seleccionado
    7. Enviar respuesta al canal de Discord
    8. Guardar en la tabla messages

    Configuración:
    - DISCORD_BOT_TOKEN: Token del bot desde Discord Developer Portal
    - DISCORD_CHANNEL_ID: Canal por defecto para respuestas
    - URL: https://tu-dominio.com/api/v1/webhooks/discord
    """
    # Discord envía un GET con challenge al configurar el webhook
    if request.method == "GET":
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        if mode == "subscribe" and token == "neuralcrew_verify_token":
            return {"challenge": challenge}
        return {"status": "error", "message": "Verify token inválido"}

    payload = await request.json()
    headers = dict(request.headers)

    try:
        channel = _get_channel("discord")

        # Validar webhook con headers
        validation = await channel.validate_webhook(payload, headers)
        if not validation.get("valid"):
            logger.warning(f"Webhook de Discord no válido: {validation.get('reason')}")
            return {"status": "error", "message": f"Webhook no validado: {validation.get('reason')}"}

        # Resolver tenant_id desde channel_mappings
        tenant_id = _resolve_tenant_id("discord", payload)

        result = await channel.handle_webhook(
            raw_payload=payload,
            tenant_id=tenant_id,
        )

        return result

    except Exception as e:
        logger.error(f"Error en webhook de Discord: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Endpoint de webhook de WhatsApp (Meta Business API).

    Meta envía un GET con challenge al configurar el webhook,
    y POST cuando llegan mensajes entrantes.

    Flujo:
    1. Validar challenge (GET) o firma HMAC-SHA256 (POST)
    2. Extraer from (número), nombre, texto del mensaje
    3. Resolver tenant_id desde channel_mappings
    4. Llamar a Ragnar.decide() para routing
    5. Ejecutar el módulo seleccionado
    6. Enviar respuesta por WhatsApp
    7. Guardar en la tabla messages

    Configuración:
    - WHATSAPP_PHONE_NUMBER_ID: ID del número de WhatsApp Business
    - WHATSAPP_ACCESS_TOKEN: Token de acceso de la app de Facebook
    - WHATSAPP_APP_SECRET: App secret para firma HMAC-SHA256
    - URL: https://tu-dominio.com/api/v1/webhooks/whatsapp
    """
    # Meta envía un GET con challenge al configurar el webhook
    if request.method == "GET":
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        if mode == "subscribe" and token == "neuralcrew_verify_token":
            return {"challenge": challenge}
        return {"challenge": challenge}

    payload = await request.json()
    headers = dict(request.headers)

    try:
        channel = _get_channel("whatsapp")

        # Validar webhook con headers (para firma HMAC-SHA256)
        validation = await channel.validate_webhook(payload, headers)
        if not validation.get("valid"):
            logger.warning(f"Webhook de WhatsApp no válido: {validation.get('reason')}")
            return {"status": "error", "message": f"Webhook no validado: {validation.get('reason')}"}

        # Resolver tenant_id desde channel_mappings
        tenant_id = _resolve_tenant_id("whatsapp", payload)

        result = await channel.handle_webhook(
            raw_payload=payload,
            tenant_id=tenant_id,
        )

        return result

    except Exception as e:
        logger.error(f"Error en webhook de WhatsApp: {e}")
        return {"status": "error", "message": str(e)}
