"""
Schemas Pydantic para Auth.

Manejan los datos de autenticación del sistema.

NOTA: La autenticación principal se maneja con Clerk (servicio externo).
Los schemas aquí son para respuestas internas del sistema.
"""

from pydantic import BaseModel, Field
from uuid import UUID


class AuthResponse(BaseModel):
    """Datos de autenticación devueltos al cliente"""
    authenticated: bool
    user_id: str
    tenant_id: UUID
    tenant_name: str
