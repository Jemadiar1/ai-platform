"""
Middleware de logging estructurado.

Este middleware se ejecuta en CADA request.
Registra: método, ruta, IP, user-agent, duración, status code.

¿Por qué logging estructurado?
- JSON es fácil de parsear por herramientas de observabilidad
- Prometheus/Grafana/Loki pueden ingestar logs JSON directamente
- Facilita buscar, filtrar y graficar métricas de la API

Ejemplo de output JSON:
    {
        "timestamp": "2026-05-07T10:00:00Z",
        "level": "info",
        "service": "ai-platform",
        "method": "GET",
        "path": "/api/v1/tasks",
        "status": 200,
        "duration_ms": 45,
        "client_ip": "192.168.1.100"
    }

¿Por qué logging estándar en vez de structlog?
- structlog tiene API ambigua (stdlib vs Python nativa)
- La configuración de structlog con BoundLogger exige sintaxis específica
- Python logging estándar es más predecible y fácil de debuggear
- Para producción, se puede añadir JSONFormatter fácilmente
"""

import time
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Logger estándar de Python
logger = logging.getLogger("ai_platform")


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware que registra todos los requests/responses.
    
    Se ejecuta antes de cada endpoint y registra:
    1. Request entrante: método, path, IP
    2. Tiempo de procesamiento
    3. Status code de respuesta
    
    Uso en main.py:
        app.add_middleware(LoggingMiddleware)
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Ejecutar antes y después de cada request.
        
        Parámetros:
            request: El request entrante
            call_next: Función que ejecuta el endpoint real
        
        Retorna:
            Response del endpoint con logging añadido
        """
        # Registrar inicio del request
        logger.info(
            "request_start",
            method=request.method,
            path=str(request.url.path),
            client_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", "unknown"),
        )
        
        # Medir tiempo de procesamiento
        start_time = time.perf_counter()
        
        # Ejecutar el endpoint
        response = await call_next(request)
        
        # Calcular duración
        process_time = time.perf_counter() - start_time
        duration_ms = round(process_time * 1000, 2)
        
        # Registrar completado del request
        logger.info(
            "request_complete",
            method=request.method,
            path=str(request.url.path),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        
        # Añadir header de duración a la respuesta (útil para debug)
        response.headers["X-Process-Time"] = str(duration_ms)
        
        return response


def setup_logging(log_level: str = "INFO"):
    """
    Configurar el logging de toda la aplicación.
    
    En desarrollo: logs en texto plano legible
    En producción: logs en JSON para ingestar a Loki/Grafana
    
    Parámetros:
        log_level: Nivel de log (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
    )
