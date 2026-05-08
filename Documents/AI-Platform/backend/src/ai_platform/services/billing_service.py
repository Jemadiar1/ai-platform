"""
Servicio de facturación con Stripe.

Stripe es el sistema de pagos que maneja:
- Suscripciones mensuales/anuales
- Facturación automática
- Métodos de pago (tarjetas, transferencias, etc.)
- Webhooks (eventos de pago)
- Pruebas gratis (free trials)
- Cupones y descuentos
- Facturas PDF

¿Por qué Stripe?
- Es el estándar de la industria para SaaS
- Maneja impuestos (VAT, sales tax) automáticamente
- Soporta múltiples monedas
- $25/mes vs. mantener tu propio sistema de billing
- Seguridad PCI compliance incluido

Modos de operación:
    - Producción: Usar Stripe API real
    - Desarrollo: Usar Stripe Test Mode (mock payments)

Flujo de integración:
    1. Cliente se suscribe desde el dashboard
    2. Stripe crea un customer_id y subscription_id
    3. Stripe envía webhooks a nuestro backend
    4. Actualizamos el plan del tenant en nuestra BD
    5. Mostramos el plan actual en el dashboard
"""

from fastapi import Request, HTTPException, status
import functools
import httpx
import stripe
from ai_platform.core.config import get_settings
from ai_platform.database import session_factory
from ai_platform.models.db import Tenant, UsageEvent
from sqlalchemy.exc import OperationalError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Optional, Dict, Any

settings = get_settings()


def retry_db_operations(max_attempts: int = 3):
    """
    Decorador para reintentar operaciones de base de datos fallidas.

    Se aplica a métodos que ejecutan queries SQL para manejar
    errores transitorios como conexiones perdidas o timeouts.

    Parámetros:
        max_attempts: Número máximo de intentos (default: 3)

    Retorna:
        Decorador con lógica de reintentos exponenciales
    """
    def decorator(func):
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(OperationalError),
            reraise=True,
        )
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator


class BillingService:
    """
    Servicio para interactuar con Stripe.
    
    Encapsula todas las operaciones relacionadas con:
    - Gestión de suscripciones
    - Facturación
    - Webhooks de pago
    - Actualización de planes
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.STRIPE_SECRET_KEY
        self.api_url = "https://api.stripe.com/v1"
        
        if not self.api_key:
            # Modo desarrollo sin Stripe configurado
            self.api_key = "sk_test_dummy_for_development"
        
        # Configurar Stripe SDK
        stripe.api_key = self.api_key

    @retry_db_operations()
    def get_stripe_customer(self, tenant_id: str, clerk_user_id: Optional[str] = None) -> Optional[dict]:
        """
        Buscar o crear un cliente de Stripe asociado a un tenant.
        
        Primero busca en nuestra BD si ya existe un stripe_customer_id.
        Si no existe, crea uno nuevo en Stripe y lo guarda.
        
        Parámetros:
            tenant_id: ID del tenant en nuestra BD
            clerk_user_id: ID del usuario en Clerk (opcional, para búsqueda alternativa)
        
        Retorna:
            Diccionario con datos del customer de Stripe o None si falla
        """
        session = session_factory()
        try:
            tenant = session.query(Tenant).filter(
                (Tenant.id == tenant_id) | (Tenant.clerk_user_id == clerk_user_id)
            ).first()
            
            if not tenant:
                return None

            # Si ya tiene un customer_id de Stripe, devolverlo
            if tenant.settings and isinstance(tenant.settings, dict):
                stripe_customer_id = tenant.settings.get("stripe_customer_id")
                if stripe_customer_id:
                    try:
                        customer = stripe.Customer.retrieve(stripe_customer_id)
                        return {
                            "id": customer.id,
                            "email": customer.email,
                            "stripe_customer_id": stripe_customer_id,
                            "exists": True
                        }
                    except stripe.StripeError as e:
                        return None

            # Buscar cliente por email en Stripe
            stripe_customer = None
            if tenant.billing_email:
                try:
                    customers = stripe.Customer.search(query=f'email:"{tenant.billing_email}"')
                    if customers.data:
                        stripe_customer = customers.data[0]
                except stripe.StripeError:
                    pass

            # Crear nuevo cliente en Stripe si no existe
            if not stripe_customer:
                try:
                    stripe_customer = stripe.Customer.create(
                        email=tenant.billing_email or "",
                        name=tenant.name or "",
                        metadata={"tenant_id": str(tenant.id), "clerk_user_id": tenant.clerk_user_id or ""}
                    )
                except stripe.StripeError as e:
                    return None

            # Guardar el customer_id en la BD del tenant
            if not tenant.settings or not isinstance(tenant.settings, dict):
                tenant.settings = {}
            tenant.settings["stripe_customer_id"] = stripe_customer.id
            session.commit()

            return {
                "id": stripe_customer.id,
                "email": stripe_customer.email,
                "stripe_customer_id": stripe_customer.id,
                "exists": True
            }
        except Exception as e:
            session.rollback()
            return None
        finally:
            session.close()
    
    def verify_webhook_signature(self, payload: bytes, sig: str, secret: Optional[str] = None) -> dict:
        """
        Verificar la firma de un webhook de Stripe.
        
        Usa stripe.webhooks.construct_event() para validar que el webhook
        viene realmente de Stripe y no de un atacante fakeando requests.
        
        Parámetros:
            payload: Body raw del request (bytes)
            sig: Header Stripe-Signature
            secret: Webhook secret (usa el de settings si no se proporciona)
        
        Retorna:
            Diccionario con "valid": bool y "event": dict o None
        
        Raises:
            ValueError: Si la firma no es válida
            HTTPException: Si el payload no es JSON parseable
        """
        webhook_secret = secret or self.settings.STRIPE_WEBHOOK_SECRET
        
        if not webhook_secret:
            logger.warning("webhook_secret no configurado, rechazando webhook")
            return {"valid": False, "error": "webhook_secret no configurado"}
        
        try:
            event = stripe.webhooks.construct_event(payload, sig, webhook_secret)
            return {"valid": True, "event": event}
        except stripe.error.SignatureVerificationError:
            return {"valid": False, "error": "firma_inválida"}
    
    async def get_customer(self, clerk_user_id: str) -> Optional[dict]:
        """
        Obtener el customer de Stripe asociado a un usuario.
        
        Parámetros:
            clerk_user_id: ID del usuario en Clerk
        
        Retorna:
            Diccionario con datos del customer o None si no existe
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_url}/customers",
                    headers=headers,
                    params={"expand": ["data.subscriptions"]}
                )
                
                if response.status_code == 200:
                    return response.json()
                return None
        except httpx.HTTPError:
            return None
    
    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        tenant_id: str
    ) -> dict:
        """
        Crear una nueva suscripción.
        
        Parámetros:
            customer_id: ID del customer en Stripe
            price_id: ID del precio (plan) en Stripe
            tenant_id: ID del tenant en nuestra BD
        
        Retorna:
            Diccionario con datos de la suscripción
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/subscriptions",
                    headers=headers,
                    data={
                        "customer": customer_id,
                        "price": price_id,
                        "metadata": {"tenant_id": tenant_id}
                    }
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Stripe API error: status={response.status_code}, body={response.text}")
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Error al procesar la solicitud con Stripe. Intente nuevamente."
                    )
        except httpx.HTTPError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Error al conectar con Stripe"
            )
    
    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        """
        Procesar un webhook de Stripe.
        
        Los webhooks son notificaciones que Stripe envía cuando ocurren eventos:
        - customer.subscription.created → Nueva suscripción
        - customer.subscription.updated → Plan cambiado
        - customer.subscription.deleted → Cancelación
        - invoice.payment_succeeded → Pago exitoso
        - invoice.payment_failed → Pago fallido
        
        Parámetros:
            payload: Body del request (raw bytes)
            signature: Header Stripe-Signature para verificar autenticidad
        
        Retorna:
            Diccionario con el evento procesado
        
        IMPORTANTE:
        - Siempre verificar la firma de Stripe antes de procesar
        - Esto evita que alguien fakee webhooks
        """
        # Verificar firma del webhook con Stripe SDK
        webhook_result = self.verify_webhook_signature(payload, signature)
        
        if not webhook_result.get("valid"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Firma de webhook inválida"
            )
        
        event = webhook_result.get("event")
        
        if not event:
            return {"status": "no_event", "check": "signature_valid_passed"}
        
        event_type = event.get("type")
        data = event.get("data", {}).get("object", {})
        
        if event_type == "customer.subscription.created":
            return await self._handle_subscription_created({"data": {"object": data}})
        elif event_type == "customer.subscription.updated":
            return await self._handle_subscription_updated({"data": {"object": data}})
        elif event_type == "customer.subscription.deleted":
            return await self._handle_subscription_deleted({"data": {"object": data}})
        elif event_type == "invoice.payment_succeeded":
            return await self._handle_payment_succeeded({"data": {"object": data}})
        elif event_type == "invoice.payment_failed":
            return await self._handle_payment_failed({"data": {"object": data}})
        else:
            return {"status": "unhandled", "event": event_type}
    
    async def _handle_subscription_created(self, event: dict) -> dict:
        """Manejar nueva suscripción."""
        subscription = event.get("data", {}).get("object", {})
        tenant_id = subscription.get("metadata", {}).get("tenant_id")
        price_id = subscription.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", "")
        plan = self._extract_plan_from_price_id(price_id)
        status_value = subscription.get("status", "incomplete")
        subscription_id = subscription.get("id")
        
        if not tenant_id:
            return {"status": "error", "message": "No se encontró tenant_id en los metadatos de la suscripción"}
        
        session = session_factory()
        try:
            tenant = session.query(Tenant).filter_by(id=tenant_id).first()
            if not tenant:
                return {"status": "error", "message": "No se encontró el tenant"}
            
            old_plan = tenant.plan
            tenant.plan = plan
            tenant.is_active = status_value == "active"
            session.commit()
            
            return {
                "status": "subscription_created",
                "tenant_id": tenant_id,
                "plan": plan,
                "old_plan": old_plan,
                "subscription_id": subscription_id,
                "subscription_status": status_value
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": str(e)}
        finally:
            session.close()
    
    @retry_db_operations()
    async def _handle_subscription_updated(self, event: dict) -> dict:
        """Manejar cambio de suscripción."""
        subscription = event.get("data", {}).get("object", {})
        tenant_id = subscription.get("metadata", {}).get("tenant_id")
        price_id = subscription.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", "")
        plan = self._extract_plan_from_price_id(price_id)
        status_value = subscription.get("status", "")
        subscription_id = subscription.get("id")
        
        if not tenant_id:
            return {"status": "error", "message": "No se encontró tenant_id en los metadatos de la suscripción"}
        
        session = session_factory()
        try:
            tenant = session.query(Tenant).filter_by(id=tenant_id).first()
            if not tenant:
                return {"status": "error", "message": "No se encontró el tenant"}
            
            old_plan = tenant.plan
            tenant.plan = plan
            tenant.is_active = status_value == "active"
            session.commit()
            
            return {
                "status": "subscription_updated",
                "tenant_id": tenant_id,
                "old_plan": old_plan,
                "new_plan": plan,
                "subscription_id": subscription_id
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": str(e)}
        finally:
            session.close()
    
    @retry_db_operations()
    async def _handle_subscription_deleted(self, event: dict) -> dict:
        """Manejar cancelación de suscripción."""
        subscription = event.get("data", {}).get("object", {})
        tenant_id = subscription.get("metadata", {}).get("tenant_id")
        
        if not tenant_id:
            return {"status": "error", "message": "No se encontró tenant_id en los metadatos de la suscripción"}
        
        session = session_factory()
        try:
            tenant = session.query(Tenant).filter_by(id=tenant_id).first()
            if not tenant:
                return {"status": "error", "message": "No se encontró el tenant"}
            
            old_plan = tenant.plan
            tenant.plan = "free"
            tenant.is_active = True
            session.commit()
            
            return {
                "status": "subscription_deleted",
                "tenant_id": tenant_id,
                "old_plan": old_plan,
                "new_plan": "free"
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": str(e)}
        finally:
            session.close()
    
    async def _handle_payment_succeeded(self, event: dict) -> dict:
        """Manejar pago exitoso."""
        invoice = event.get("data", {}).get("object", {})
        tenant_id = invoice.get("metadata", {}).get("tenant_id")
        amount_paid = invoice.get("amount_paid", 0)
        currency = invoice.get("currency", "usd")
        invoice_id = invoice.get("id")
        
        if not tenant_id:
            return {"status": "error", "message": "No se encontró tenant_id en los metadatos de la factura"}
        
        return await self.record_payment(
            tenant_id=tenant_id,
            amount=amount_paid,
            currency=currency,
            invoice_id=invoice_id
        )
    
    @retry_db_operations()
    def record_payment(self, tenant_id: str, amount: int, currency: str = "usd", invoice_id: str = None) -> dict:
        """
        Registrar un pago exitoso en el sistema de usage events.
        
        Parámetros:
            tenant_id: ID del tenant que pagó
            amount: Monto pagado en centavos (ej: $10.00 = 1000)
            currency: Moneda del pago (ej: "usd", "mxn")
            invoice_id: ID de la factura de Stripe (opcional)
        
        Retorna:
            Diccionario con el resultado del registro de pago
        """
        session = session_factory()
        try:
            usage = UsageEvent(
                tenant_id=tenant_id,
                module="billing",
                event_type="payment_succeeded",
                tokens_used=0,
                cost_usd=amount / 100 if amount else 0,
                extra_data={"invoice_id": invoice_id, "currency": currency}
            )
            session.add(usage)
            session.commit()
            
            return {
                "status": "payment_recorded",
                "tenant_id": tenant_id,
                "amount": amount / 100 if amount else 0,
                "currency": currency,
                "invoice_id": invoice_id
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": str(e)}
        finally:
            session.close()
    
    @retry_db_operations()
    async def _handle_payment_failed(self, event: dict) -> dict:
        """Manejar pago fallido."""
        invoice = event.get("data", {}).get("object", {})
        tenant_id = invoice.get("metadata", {}).get("tenant_id")
        
        if not tenant_id:
            return {"status": "error", "message": "No se encontró tenant_id en los metadatos de la factura"}
        
        session = session_factory()
        try:
            tenant = session.query(Tenant).filter_by(id=tenant_id).first()
            if not tenant:
                return {"status": "error", "message": "No se encontró el tenant"}
            
            # Cambiar a plan free y marcar el evento de pago fallido
            tenant.plan = "free"
            session.commit()
            
            return {
                "status": "payment_failed",
                "tenant_id": tenant_id,
                "message": "Plan cambiado a free debido al pago fallido"
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": str(e)}
        finally:
            session.close()
    
    @retry_db_operations()
    async def get_tenant_plan(self, tenant_id: str) -> str:
        """
        Obtener el plan actual de un tenant.
        
        Parámetros:
            tenant_id: ID del tenant en nuestra BD
        
        Retorna:
            Nombre del plan actual (starter, pro, enterprise)
        """
        session = session_factory()
        try:
            tenant = session.query(Tenant).filter_by(id=tenant_id).first()
            if not tenant:
                return "starter"  # Default
            return tenant.plan
        except Exception:
            return "starter"
        finally:
            session.close()
    
    @staticmethod
    def _extract_plan_from_price_id(price_id: str) -> str:
        """
        Extraer nombre del plan desde el price_id de Stripe.
        
        Los price_id siguen el formato: price_123_starter_monthly
        """
        valid_plans = ["starter", "pro", "enterprise"]
        if not price_id:
            return "starter"
        
        parts = price_id.split("_")
        if len(parts) >= 3:
            plan_name = parts[2]
            if plan_name in valid_plans:
                return plan_name
        
        return "starter"


# Instancia global para usar en todo el servidor
billing_service = BillingService()


async def get_tenant_plan(tenant_id: str) -> str:
    """
    Dependency de FastAPI para obtener el plan actual de un tenant.
    
    Se usa en endpoints que necesitan verificar el plan:
        @app.get("/usage")
        async def usage(plan: str = Depends(get_tenant_plan)):
            return {"plan": plan}
    """
    return await billing_service.get_tenant_plan(tenant_id)
