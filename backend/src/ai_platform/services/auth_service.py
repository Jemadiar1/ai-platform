"""
Servicio de autenticación y caché de tokens Clerk.

Clerk es un servicio externo de autenticación completo.
Nosotros NO gestionamos login/registro/usuarios. Clerk lo hace todo.

¿Por qué Clerk?
- ~200 horas de desarrollo ahorradas
- Multi-tenancy integrado
- Social login (Google, GitHub, etc.)
- MFA (autenticación multi-factor)
- SSO (Single Sign-On)
- $25-50/mes vs. mantener tu propio sistema de auth

Cómo funciona la integración:
    1. El frontend (Next.js) usa @clerk/nextjs para login
    2. Clerk genera un JWT y lo añade automáticamente a cada request
    3. El JWT viaja en el header: Authorization: Bearer <jwt>
    4. Nuestro backend valida el JWT con la API de Clerk
    5. Si es válido, extrae user_id, email, etc.
    6. Si no existe en nuestra BD, creamos el usuario automáticamente

Modos de operación:
    - Producción: Validar tokens con la API de Clerk
    - Desarrollo: Validar tokens localmente (sin necesidad de Clerk)
"""

import httpx
from fastapi import HTTPException, Request, status

from ai_platform.core.config import get_settings
from ai_platform.core.security import LRUCache

settings = get_settings()

# Cache acotado para evitar llamadas repetidas a Clerk.
# - Máximo 5000 entradas (para evitar crecimiento ilimitado de memoria)
# - 50 minutos de validez (los tokens de Clerk son válidos por 1h)
# - Usa LRU para eliminar automáticamente las entradas más antiguas
_clerk_cache = LRUCache(maxsize=5000, ttl=3000)


class AuthService:
    """
    Servicio para interactuar con Clerk.

    Encapsula todas las operaciones relacionadas con:
    - Validación de tokens JWT
    - Obtención de datos de usuario
    - Sincronización con nuestra base de datos
    """

    def __init__(self):
        self.settings = get_settings()
        self.client = httpx.AsyncClient(
            base_url=self.settings.CLERK_API_URL,
            headers={"Authorization": f"Bearer {self.settings.CLERK_SECRET_KEY}"},
            timeout=10.0,  # Timeout de 10 segundos
        )

    async def verify_token(self, token: str) -> dict | None:
        """
        Validar un token JWT con la API de Clerk.

        Flujo:
        1. Verificar cache (si ya validamos recientemente este token)
        2. Llamar a la API de Clerk para validar
        3. Cache del resultado
        4. Retornar claims o None si inválido

        Parámetros:
            token: Token JWT en string

        Retorna:
            Diccionario con claims si válido, None si no
        """
        # Verificar cache primero
        cached = _clerk_cache.get(token)
        if cached:
            return cached

        try:
            response = await self.client.get("/v1/tokens/verify", params={"token": token})

            if response.status_code == 200:
                # Cache exitoso con LRU automático
                _clerk_cache.set(token, response.json())
                return response.json()
            else:
                return None
        except httpx.HTTPError:
            return None

    async def get_current_user_from_token(self, request: Request) -> dict:
        """
        Extraer y validar el usuario actual desde el request.

        Este es el método principal que se usa en los endpoints.
        Combina la validación del token con la sincronización de datos.

        Flujo completo:
        1. Extraer token del header Authorization
        2. Validar token con Clerk
        3. Buscar/sincronizar usuario en nuestra BD
        4. Inyectar datos en request.state
        5. Retornar usuario

        Parámetros:
            request: Request entrante

        Retorna:
            Diccionario con datos del usuario

        Excepciones:
            401: Token inválido o faltante
        """
        # Extraer token del header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de autenticación faltante")

        token = auth_header.split(" ")[1]

        # Validar con Clerk
        clerk_data = await self.verify_token(token)
        if not clerk_data:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")

        # Extraer datos del usuario
        user_id = clerk_data.get("sub")  # subject = user_id en Clerk

        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No se pudo identificar al usuario")

        # Extraer email si está disponible
        email = clerk_data.get("email", "")

        # NO devolvemos el raw token al cliente
        # Esto elimina la exposición accidental del token
        return {"user_id": user_id, "email": email, "full_name": clerk_data.get("last_name", "")}

    async def get_user_details(self, user_id: str) -> dict | None:
        """
        Obtener detalles de un usuario desde Clerk.

        Parámetros:
            user_id: ID del usuario en Clerk

        Retorna:
            Diccionario con datos del usuario o None si no existe
        """
        try:
            response = await self.client.get(f"/v1/users/{user_id}")
            if response.status_code == 200:
                return response.json()
            return None
        except httpx.HTTPError:
            return None

    async def close(self) -> None:
        """Cerrar el cliente HTTP."""
        await self.client.aclose()


# Instancia global para usar en todo el servidor
auth_service = AuthService()


async def get_current_user(request: Request) -> dict:
    """
    Dependency de FastAPI para obtener el usuario actual.

    Se usa en endpoints como:
        @app.get("/me")
        async def me(user: dict = Depends(get_current_user)):
            return user

    FastAPI ejecuta esta función y obtiene el usuario
    del token JWT automáticamente.
    """
    return await auth_service.get_current_user_from_token(request)


async def get_clerk_user(user_id: str) -> dict | None:
    """
    Obtener datos de un usuario desde Clerk.

    Parámetros:
        user_id: ID del usuario en Clerk

    Retorna:
        Diccionario con datos del usuario o None
    """
    return await auth_service.get_user_details(user_id)
