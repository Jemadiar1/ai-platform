"""
Endpoints del API versión 1.

Todos los endpoints están bajo /api/v1/
Cada endpoint requiere:
- Autenticación (token JWT)
- Multi-tenancy (tenant_id inyectado automáticamente)

Los routers se agrupan por resource:
- tasks.py → gestión de tareas
- tenants.py → gestión de tenants
- ping.py → health check
- webhooks.py → webhooks de Clerk y Stripe

"""

from fastapi import APIRouter

from ai_platform.api.v1.ping import router as ping_router
from ai_platform.api.v1.ragnar import router as ragnar_router
from ai_platform.api.v1.tasks import router as tasks_router
from ai_platform.api.v1.tenants import router as tenants_router
from ai_platform.api.v1.webhooks import router as webhooks_router

# Crear el router principal de la versión 1
router = APIRouter()

# Incluir routers con prefijo
router.include_router(ping_router)
router.include_router(ragnar_router, prefix="/ragnar", tags=["ragnar"])
router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
router.include_router(tenants_router, prefix="/tenants", tags=["tenants"])
router.include_router(webhooks_router)
