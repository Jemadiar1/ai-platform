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

from fastapi import APIRouter, Request, HTTPException, status
import hmac
import hashlib
import json
from datetime import datetime, timezone

from ai_platform.database import session_factory
from ai_platform.models.db import Tenant, User, UsageEvent

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
        return {"status": "error", "message": "No tenant_id in metadata"}
    
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
        return {"status": "error", "message": "No tenant_id in metadata"}
    
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
        return {"status": "error", "message": "No tenant_id in metadata"}
    
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
