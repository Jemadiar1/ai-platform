"""
Middleware de Multi-Tenancy.

Este middleware es el más crítico de seguridad del sistema.
Su trabajo es asegurarse de que cada tenant solo vea sus propios datos.

¿Qué es multi-tenancy?
- Un solo servidor sirve a múltiples clientes (tenants)
- Cada tenant es una empresa diferente
- Los datos de cada tenant DEBEN estar aislados
- Un tenant NO puede ver ni acceder a datos de otro tenant

Estrategia elegida: shared schema con tenant_id
- Todas las tablas tienen columna tenant_id
- Cada query filtra por tenant_id del tenant autenticado
- Si una query no filtra por tenant_id -> posible fuga de datos

Flujo completo:
    1. Cliente envía request con JWT de Clerk
    2. Clerk valida el JWT y añade user_id al request.state
    3. Este middleware busca el tenant asociado al user_id
    4. Inyecta tenant_id en request.state.tenant_id
    5. Cada endpoint que usa get_current_tenant() obtiene el tenant
    6. Cada query de base de datos filtra por tenant_id

Ejemplo de uso en un endpoint:
    @app.get("/my-tasks")
    def my_tasks(tenant: Tenant = Depends(get_current_tenant), db = Depends(get_db_session)):
        # Esta query SOLO busca tareas de este tenant
        tasks = db.execute(select(Task).where(Task.tenant_id == tenant.id))
        return tasks
"""

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from ai_platform.core.security import decode_token
from ai_platform.database import session_factory
from ai_platform.models.db import Tenant, User


def get_current_tenant(request: Request) -> Tenant:
    """
    Obtener el tenant actual desde el request.

    Esta función se inyecta en endpoints usando Depends(get_current_tenant).
    FastAPI la ejecuta automáticamente antes del endpoint.

    Flujo:
    1. Extraer token del header Authorization: Bearer <token>
    2. Decodificar JWT para obtener user_id
    3. Buscar el tenant del usuario en la base de datos
    4. Validar que el tenant existe y está activo
    5. Inyectar tenant_id en request.state para que esté disponible en el endpoint

    Excepciones:
    - 401: Token inválido o faltante
    - 403: Tenant no existe o está inactivo
    """
    # Extraer token del header Authorization
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de autenticación faltante o inválido"
        )

    token = auth_header.split(" ")[1]

    # Decodificar JWT para obtener user_id
    decoded = decode_token(token)
    if not decoded:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")

    # Obtener user_id del token
    user_id = decoded.get("sub") or decoded.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No se pudo identificar al usuario")

    # Buscar el tenant asociado al usuario
    session = session_factory()
    try:
        # Buscar usuario por clerk_user_id para obtener su tenant
        user_result = session.execute(select(User).where(User.clerk_user_id == user_id))
        user = user_result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no registrado en el sistema")

        # Buscar el tenant de este usuario
        tenant_result = session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = tenant_result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant no encontrado")

        if not tenant.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant inactivo. Contacta soporte.")

        # Inyectar tenant_id en request.state para usarlo en otros middlewares/endpoint
        request.state.tenant_id = tenant.id
        request.state.tenant = tenant
        request.state.user_id = user.id

        return tenant
    finally:
        session.close()


def tenant_middleware(request: Request, call_next):
    """
    Middleware que valida tenant en CADA request.

    Se registra en main.py y se ejecuta automáticamente antes de cada endpoint.
    Asegura que tenant_id esté disponible en request.state.
    """
    # Obtener tenant (genera dependencia si no existe)
    get_current_tenant(request)

    response = call_next(request)
    return response
