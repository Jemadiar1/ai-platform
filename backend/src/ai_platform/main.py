"""
Entry point principal de la aplicación.

Este archivo es el corazón del backend. Aquí se configura FastAPI
y se conectan todas las piezas del sistema.

Arquitectura general:
    Request -> Middleware (logging, tenant, auth) -> Router -> Endpoint -> Response

FastAPI se encarga de:
- Servir la API en el puerto 4000
- Generar Swagger UI automáticamente en /docs
- Validar requests/responses con Pydantic
- Manejar CORS entre Next.js (3000-3002) y la API (4000)
- Inyectar dependencias (Base de datos, Tenant, Auth)

¿Por qué este orden importa?
1. CORS middleware se añade primero (para que todo el request pase)
2. Logging middleware se añade segundo (para medir cada request)
3. Los routers van al final (para que tengan acceso a todo lo configurado)

NOTA: En desarrollo, la conexión a BD se verifica en el endpoint /health.
Si la BD no está disponibles el servidor igual arranca, pero los endpoints
que requieren BD devolverán 500.
"""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_platform.api.v1.routers import router as v1_router
from ai_platform.core.config import get_settings
from ai_platform.middleware.logging import LoggingMiddleware
from ai_platform.orchestrator.cron_manager import get_cron_manager


def _validate_production_config() -> None:
    """
    Validar configuración requerida en producción.

    Fail-fast: si falta SECRET_KEY en producción, la app no arranca.
    Esto evita firmar tokens con una clave conocida por defecto.
    """
    settings = get_settings()
    if settings.is_production and not settings.SECRET_KEY:
        raise RuntimeError(
            "FATAL: SECRET_KEY debe estar configurada en producción. Verifica tu .env o las variables de entorno."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida de la aplicación.

    AL INICIO (startup): Validar configuración, iniciar servicios.
    AL FINAL (shutdown): Detener servicios limpiamente.

    La conexión a BD se verifica en runtime en el endpoint /health.
    """
    _validate_production_config()
    settings = get_settings()
    print("=" * 60)
    print("[INFO] NeuralCrew Labs API v1")
    print(f"[INFO] Environment: {settings.ENVIRONMENT.value}")
    print("[INFO] Docs: http://localhost:4000/docs")
    print("[INFO] Redoc: http://localhost:4000/redoc")
    print("=" * 60)

    # Iniciar scheduler de cron jobs en background
    cron_mgr = get_cron_manager()
    scheduler_task = asyncio.create_task(cron_mgr.start_scheduler())
    app.state.scheduler_task = scheduler_task

    yield

    # Shutdown: detener scheduler limpiamente
    scheduler_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await scheduler_task

    print("[INFO] Shutting down API")


# Crear la aplicación FastAPI
app = FastAPI(
    title="NeuralCrew Labs API",
    description="Plataforma de marketing impulsada por IA - v1",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Configurar CORS (Cross-Origin Resource Sharing)
settings = get_settings()
cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurar middleware de logging
app.add_middleware(LoggingMiddleware)

# Incluir los routers de la API
app.include_router(v1_router, prefix="/api/v1")
