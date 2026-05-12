"""
Schemas Pydantic para Auth.

Manejan los datos de autenticación del sistema.

NOTA: La autenticación principal se maneja con Clerk (servicio externo).
Los schemas aquí son para respuestas internas del sistema.
"""

from uuid import UUID

from pydantic import BaseModel


class AuthResponse(BaseModel):
    """Datos de autenticación devueltos al cliente"""

    authenticated: bool
    user_id: str
    tenant_id: UUID
    tenant_name: str
