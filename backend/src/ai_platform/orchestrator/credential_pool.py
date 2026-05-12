"""
Pool de credenciales reutilizables.

Inspirado en Hermes Agent's credential_pool.py.
Gestiona API keys, tokens, y credenciales de providers.

Patrones de Hermes aplicados:
- Pool centralizado de credenciales
- Rotación automática de credenciales expiradas
- Tracking de uso por provider
- Carga desde variables de entorno (settings)
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Credential:
    """Credencial de un provider."""

    provider: str
    key: str
    created_at: datetime
    expires_at: datetime | None = None
    last_used: datetime | None = None
    usage_count: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


class CredentialPool:
    """
    Pool centralizado de credenciales para providers externos.

    Gestiona:
    - API keys para OpenRouter, Stripe, WhatsApp, Vapi, etc.
    - Rotación automática de credenciales expiradas
    - Tracking de uso por provider
    """

    def __init__(self):
        self._credentials: dict[str, Credential] = {}
        self._load_from_config()

    def _load_from_config(self):
        """Cargar credenciales desde settings (variables de entorno)."""
        from ai_platform.core.config import get_settings

        settings = get_settings()

        self._set_if_present("openrouter", settings.OPENROUTER_API_KEY)
        self._set_if_present("stripe", settings.STRIPE_SECRET_KEY)
        self._set_if_present("whatsapp", settings.WHATSAPP_ACCESS_TOKEN)
        self._set_if_present("vapi", settings.VAPI_API_KEY)

    def _set_if_present(self, provider: str, key: str | None):
        """Registrar credencial si la clave está presente."""
        if key:
            self._credentials[provider] = Credential(
                provider=provider,
                key=key,
                created_at=datetime.now(UTC),
            )

    async def get(self, provider: str) -> str | None:
        """
        Obtener credencial para un provider.

        Verifica expiración y actualiza tracking de uso.

        Parámetros:
            provider: Nombre del provider (ej: "openrouter", "stripe")

        Retorna:
            La API key como string, o None si no existe o está expirada
        """
        cred = self._credentials.get(provider)
        if not cred:
            return None

        # Verificar expiración
        if cred.expires_at and cred.expires_at < datetime.now(UTC):
            logger.warning(f"Credential expired for provider: {provider}")
            del self._credentials[provider]
            return None

        # Actualizar tracking de uso
        cred.last_used = datetime.now(UTC)
        cred.usage_count += 1

        return cred.key

    async def register_provider_credential(self, provider: str, key: str):
        """
        Registrar credenciales adicionales para un provider.

        Permite registrar nuevas credenciales en runtime
        sin reiniciar la aplicación.

        Parámetros:
            provider: Nombre del provider
            key: La API key o token
        """
        self._credentials[provider] = Credential(
            provider=provider,
            key=key,
            created_at=datetime.now(UTC),
        )
        logger.info(f"Registered credential for provider: {provider}")

    async def get_all_providers(self) -> dict[str, str]:
        """
        Listar todos los providers disponibles.

        Retorna:
            Dict con provider name y key enmascarada (****last4)
        """
        return {p: "****" + cred.key[-4:] for p, cred in self._credentials.items()}


# Instancia global
_credential_pool: CredentialPool | None = None


def get_credential_pool() -> CredentialPool:
    """
    Obtener pool de credenciales (singleton).

    Retorna:
        Instancia de CredentialPool
    """
    global _credential_pool
    if _credential_pool is None:
        _credential_pool = CredentialPool()
    return _credential_pool
