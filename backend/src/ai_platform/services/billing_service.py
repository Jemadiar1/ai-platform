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


import httpx
from fastapi import HTTPException, status

from ai_platform.core.config import get_settings

settings = get_settings()


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

    async def get_customer(self, clerk_user_id: str) -> dict | None:
        """
        Obtener el customer de Stripe asociado a un usuario.

        Parámetros:
            clerk_user_id: ID del usuario en Clerk

        Retorna:
            Diccionario con datos del customer o None si no existe
        """
        # TODO: Buscar customer_id en nuestra BD
        # Por ahora, buscamos por metadata
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_url}/customers", headers=headers, params={"expand": ["data.subscriptions"]}
                )

                if response.status_code == 200:
                    return response.json()
                return None
        except httpx.HTTPError:
            return None

    async def create_subscription(self, customer_id: str, price_id: str, tenant_id: str) -> dict:
        """
        Crear una nueva suscripción.

        Parámetros:
            customer_id: ID del customer en Stripe
            price_id: ID del precio (plan) en Stripe
            tenant_id: ID del tenant en nuestra BD

        Retorna:
            Diccionario con datos de la suscripción

        Ejemplo de price_id:
            - "price_123456_starter" → Plan Starter
            - "price_789012_pro" → Plan Pro
        """
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/x-www-form-urlencoded"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/subscriptions",
                    headers=headers,
                    data={"customer": customer_id, "price": price_id, "metadata": {"tenant_id": tenant_id}},
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Stripe error: {response.text}"
                    )
        except httpx.HTTPError:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Error al conectar con Stripe") from None

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
        # TODO: Verificar firma con stripe.webhooks.construct_event
        # Por ahora, procesamos directamente

        try:
            import json

            event_data = json.loads(payload)
            event_type = event_data.get("type")

            if event_type == "customer.subscription.created":
                return await self._handle_subscription_created(event_data)
            elif event_type == "customer.subscription.updated":
                return await self._handle_subscription_updated(event_data)
            elif event_type == "customer.subscription.deleted":
                return await self._handle_subscription_deleted(event_data)
            elif event_type == "invoice.payment_succeeded":
                return await self._handle_payment_succeeded(event_data)
            elif event_type == "invoice.payment_failed":
                return await self._handle_payment_failed(event_data)
            else:
                return {"status": "unhandled", "event": event_type}

        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload inválido") from None

    async def _handle_subscription_created(self, event: dict) -> dict:
        """Manejar nueva suscripción."""
        subscription = event.get("data", {}).get("object", {})
        tenant_id = subscription.get("metadata", {}).get("tenant_id")
        plan = subscription.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", "").split("_")[2]

        # TODO: Actualizar plan del tenant en nuestra BD
        return {"status": "subscription_created", "tenant_id": tenant_id, "plan": plan}

    async def _handle_subscription_updated(self, event: dict) -> dict:
        """Manejar cambio de suscripción."""
        subscription = event.get("data", {}).get("object", {})
        tenant_id = subscription.get("metadata", {}).get("tenant_id")

        # TODO: Actualizar plan del tenant en nuestra BD
        return {"status": "subscription_updated", "tenant_id": tenant_id}

    async def _handle_subscription_deleted(self, event: dict) -> dict:
        """Manejar cancelación de suscripción."""
        subscription = event.get("data", {}).get("object", {})
        tenant_id = subscription.get("metadata", {}).get("tenant_id")

        # TODO: Cambiar plan a "free" en nuestra BD
        return {"status": "subscription_deleted", "tenant_id": tenant_id}

    async def _handle_payment_succeeded(self, event: dict) -> dict:
        """Manejar pago exitoso."""
        invoice = event.get("data", {}).get("object", {})
        tenant_id = invoice.get("metadata", {}).get("tenant_id")

        # TODO: Registrar pago exitoso
        return {"status": "payment_succeeded", "tenant_id": tenant_id}

    async def _handle_payment_failed(self, event: dict) -> dict:
        """Manejar pago fallido."""
        invoice = event.get("data", {}).get("object", {})
        tenant_id = invoice.get("metadata", {}).get("tenant_id")

        # TODO: Notificar al tenant y cambiar a plan "free"
        return {"status": "payment_failed", "tenant_id": tenant_id}

    async def get_tenant_plan(self, tenant_id: str) -> str:
        """
        Obtener el plan actual de un tenant.

        Parámetros:
            tenant_id: ID del tenant en nuestra BD

        Retorna:
            Nombre del plan actual (starter, pro, enterprise)
        """
        # TODO: Buscar en nuestra BD
        return "starter"  # Default


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
