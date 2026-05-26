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
- web_research.py → investigación web interna
- documents.py → ingestión de documentos

"""

from fastapi import APIRouter

from ai_platform.api.v1.documents import router as documents_router
from ai_platform.api.v1.feedback import router as feedback_router
from ai_platform.api.v1.kb import router as kb_router
from ai_platform.api.v1.odin import router as odin_router
from ai_platform.api.v1.ping import router as ping_router
from ai_platform.api.v1.reports import router as reports_router
from ai_platform.api.v1.tasks import router as tasks_router
from ai_platform.api.v1.tenants import router as tenants_router
from ai_platform.api.v1.web_research import router as web_research_router
from ai_platform.api.v1.webhooks import router as webhooks_router

# Crear el router principal de la versión 1
router = APIRouter()

# Incluir routers con prefijo
router.include_router(ping_router)
router.include_router(odin_router, prefix="/odin", tags=["odin"])
router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
router.include_router(tenants_router, prefix="/tenants", tags=["tenants"])
router.include_router(web_research_router, prefix="/web_research", tags=["web_research"])
router.include_router(documents_router, prefix="/documents", tags=["documents"])
router.include_router(reports_router, prefix="/reports", tags=["reports"])
router.include_router(webhooks_router)
router.include_router(kb_router)
router.include_router(feedback_router)
