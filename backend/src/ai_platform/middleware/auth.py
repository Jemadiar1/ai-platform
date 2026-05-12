"""
Middleware de autenticación con Clerk.

Clerk es un servicio externo de autenticación.
Nosotros NO gestionamos login/registro. Clerk lo hace.

Cómo funciona la integración:
    1. El frontend (Next.js) usa @clerk/nextjs para login
    2. Clerk genera un JWT y lo añade automáticamente a cada request
    3. El JWT viaja en el header: Authorization: Bearer <jwt>
    4. Este middleware valida el JWT con Clerk
    5. Si es válido, extrae los claims (user_id, email, etc.)
    6. Si es inválido, bloquea el request con 401

¿Por qué Clerk?
- ~200 horas de desarrollo ahorradas
- Multi-tenancy integrado
- Social login (Google, GitHub, etc.)
- MFA (autenticación multi-factor)
- $25-50/mes vs. mantener tu propio sistema de auth
"""

from fastapi import Request, HTTPException, Depends, status
import httpx
from ai_platform.core.config import get_settings

settings = get_settings()


async def verify_clerk_token(request: Request) -> dict:
    """
    Verificar un token JWT con Clerk.
    
    Flujo:
    1. Extraer token del header Authorization: Bearer <jwt>
    2. Enviar el token a Clerk para validación
    3. Si Clerk responde 200 → token válido
    4. Si Clerk responde 401 → token inválido, bloquear request
    
    Esta función funciona DE dos formas:
    
    a) Modo Clerk directo (producción):
       Clerk valida el token y nosotros solo verificamos la respuesta
    
    b) Modo JWT local (desarrollo sin Clerk):
       Si no hay Clerk API Key, verificamos el JWT localmente
    
    Parámetros:
        request: Request entrante con el token en header
    
    Retorna:
        dict con claims del token si es válido
    
    Excepciones:
    - 401: Token inválido
    """
    # Extraer token
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación faltante"
        )
    
    token = auth_header.split(" ")[1]
    
    # Modo 1: Validar con Clerk (producción)
    if settings.CLERK_SECRET_KEY:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.CLERK_API_URL}/v1/tokens/verify",
                params={"token": token},
                headers={"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"}
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token inválido según Clerk"
                )
    
    # Modo 2: Validar localmente (desarrollo sin Clerk)
    from ai_platform.core.security import decode_token
    decoded = decode_token(token)
    
    if not decoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado"
        )
    
    return decoded
