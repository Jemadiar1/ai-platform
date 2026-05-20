"""
Configuración de la aplicación.

Usamos pydantic-settings para leer variables de entorno de forma tipada.
Esto reemplaza el patrón de `os.environ.get()` con validación automática.

¿Por qué pydantic-settings?
- Las variables de entorno son strings, necesitamos validar y convertir tipos
- Pydantic valida que todas las vars necesarias existan al iniciar
- Si falta una variable obligatoire, la app falla al arrancar (fail fast)
- Genera documentación automática del esquema de configuración

Ejemplo de archivo .env:
    DATABASE_URL=postgresql://user:pass@localhost:5432/ai_platform
    REDIS_URL=redis://localhost:6379
    SECRET_KEY=mi-secreto-super-seguro
    JWT_EXPIRATION_HOURS=24
"""

from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Entornos soportados: desarrollo, staging, producción"""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """
    Configuración principal de la aplicación.

    Todas las variables se leen del archivo .env o de variables de entorno.
    Pydantic valida los tipos automáticamente al leerlos.
    """

    model_config = SettingsConfigDict(
        env_file=".env",  # Leer desde archivo .env si existe
        env_file_encoding="utf-8",
        case_sensitive=False,  # DATABASE_URL o database_url funcionan igual
        extra="ignore",  # Ignorar variables de entorno no definidas aquí
    )

    # === Entorno ===
    ENVIRONMENT: Environment = Field(default=Environment.DEVELOPMENT)
    DEBUG: bool = Field(default=True)

    # === Base de datos ===
    DATABASE_URL: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/ai_platform",
        description="URL de conexión a PostgreSQL (async)",
    )

    # === Redis ===
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="URL de conexión a Redis")

    # === Seguridad ===
    SECRET_KEY: str | None = Field(default=None, description="Clave secreta para firmar JWT (requerido en producción)")
    JWT_EXPIRATION_HOURS: int = Field(default=24)
    JWT_ALGORITHM: str = Field(default="HS256")

    # === Clerk (Auth externa) ===
    CLERK_SECRET_KEY: str | None = None
    CLERK_API_URL: str = Field(default="https://api.clerk.com")

    # === Stripe (Billing) ===
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None

    # === LLM ===
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_API_URL: str = Field(default="https://openrouter.ai/api/v1")

    # === NaN Builders (Custom GPU) ===
    NAN_API_KEY: str | None = None
    NAN_API_URL: str = Field(default="https://api.nan.builders/v1")

    # === LLM Selection ===
    LLM_PROVIDER: str = Field(default="openrouter")  # openrouter o nan
    PRIMARY_MODEL: str | None = None
    FALLBACK_MODEL: str | None = None
    FAST_MODEL: str | None = None

    # === WhatsApp API ===
    WHATSAPP_PHONE_NUMBER_ID: str | None = None
    WHATSAPP_ACCESS_TOKEN: str | None = None
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str | None = None
    WHATSAPP_APP_SECRET: str | None = None

    # === Telegram API ===
    TELEGRAM_BOT_TOKEN: str | None = None

    # === Discord API ===
    DISCORD_BOT_TOKEN: str | None = None
    DISCORD_CHANNEL_ID: str | None = None

    # === Vapi.ai (Voz IA) ===
    VAPI_API_KEY: str | None = None

    # === Logging ===
    LOG_LEVEL: str = Field(default="INFO")

    # === CORS ===
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:3001,http://localhost:3002",
        description="Orígenes permitidos para CORS, separados por coma",
    )

    # === Prompt Caching ===
    USE_PROMPT_CACHE: bool = Field(
        default=True, description="Habilitar prompt caching para modelos Claude (ahorro 75% en costos)"
    )

    @property
    def is_production(self) -> bool:
        """Verificar si estamos en producción"""
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        """Verificar si estamos en desarrollo"""
        return self.ENVIRONMENT == Environment.DEVELOPMENT


# Instancia global de configuración
_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Obtener la instancia de configuración.
    Patrón singleton: se lee UNA SOLA VEZ y se reutiliza.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
