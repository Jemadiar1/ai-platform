"""
Tracker de límites de tasa para APIs externas.

Implementa tracking de límites de:
- OpenRouter (rate limits por modelo)
- Stripe (100 req/minute)
- WhatsApp (varía por tier)
- Vapi.ai (rate limits por minuto)

Inspirado en rate_limit_tracker.py de Hermes.

Patrones implementados:
- Ventana deslizante (sliding window) para tracking de requests
- Thread-safe con locks
- Rate limiting por servicio con límites configurables
- Auto-expiración de timestamps viejos
- Wait-if-needed con tiempo máximo de espera
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from threading import Lock
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class RateLimit:
    """
    Límite de tasa para una API.

    Define cuántas requests puede hacer un servicio
    en una ventana de tiempo dada.

    Parámetros:
        max_requests: Número máximo de requests en la ventana
        window_seconds: Duración de la ventana en segundos
        retry_after: Tiempo sugerido antes de reintentar (opcional)
    """

    max_requests: int
    window_seconds: int
    retry_after: Optional[float] = None

    def is_exceeded(self, timestamps: List[float]) -> bool:
        """
        Verificar si se excedió el límite de tasa.

        Usa ventana deslizante: solo cuenta los timestamps
        dentro de la ventana actual.

        Parámetros:
            timestamps: Lista de timestamps de requests anteriores

        Retorna:
            True si se excedió el límite
        """
        now = time.time()
        recent = [t for t in timestamps if t > now - self.window_seconds]
        return len(recent) >= self.max_requests

    def get_remaining(self, timestamps: List[float]) -> int:
        """
        Número de requests restantes en la ventana actual.

        Parámetros:
            timestamps: Lista de timestamps de requests anteriores

        Retorna:
            Número de requests restantes (mínimo 0)
        """
        now = time.time()
        recent = [t for t in timestamps if t > now - self.window_seconds]
        return max(0, self.max_requests - len(recent))

    def get_retry_after(self, timestamps: List[float]) -> float:
        """
        Calcular cuánto tiempo esperar antes de hacer otra request.

        Si se excedió el límite, calcula cuánto tiempo esperar
        hasta que el oldest timestamp salga de la ventana.

        Parámetros:
            timestamps: Lista de timestamps de requests anteriores

        Retorna:
            Segundos a esperar (0 si no necesita esperar)
        """
        now = time.time()
        recent = sorted([t for t in timestamps if t > now - self.window_seconds])
        if len(recent) >= self.max_requests:
            oldest = recent[0]
            return max(0, oldest + self.window_seconds - now)
        return 0


class RateLimitTracker:
    """
    Tracker global de límites de tasa.

    Mantiene un registro de todas las requests hechas a cada servicio
    y aplica rate limiting según los límites configurados.

    Uso:
        tracker = get_rate_limit_tracker()
        tracker.wait_if_needed("openrouter")
        # ... hacer request ...
        tracker.record_request("openrouter", success=True)
        remaining = tracker.check_remaining("openrouter")
    """

    # Límites por servicio
    # Estos valores son basados en los límites reales de cada API
    RATE_LIMITS = {
        "openrouter": RateLimit(max_requests=1000, window_seconds=60),
        "stripe": RateLimit(max_requests=100, window_seconds=60),
        "whatsapp": RateLimit(max_requests=50, window_seconds=60),
        "vapi": RateLimit(max_requests=60, window_seconds=60),
    }

    def __init__(self):
        self._timestamps: Dict[str, List[float]] = defaultdict(list)
        self._lock = Lock()

    def record_request(self, service: str, success: bool = True) -> None:
        """
        Registrar una solicitud a un servicio.

        Añade un timestamp a la lista de requests del servicio
        y limpia los timestamps viejos que salieron de la ventana.

        Parámetros:
            service: Nombre del servicio (ej: "openrouter")
            success: Si la request fue exitosa (para logging)
        """
        with self._lock:
            now = time.time()
            self._timestamps[service].append(now)

            # Limpiar timestamps viejos
            limit = self.RATE_LIMITS.get(service)
            if limit:
                cutoff = now - limit.window_seconds
                self._timestamps[service] = [
                    t for t in self._timestamps[service] if t > cutoff
                ]

            if not success:
                logger.warning(f"Request failed for {service}")

    def check_remaining(self, service: str) -> Dict[str, int]:
        """
        Verificar cuántas requests quedan en la ventana actual.

        Parámetros:
            service: Nombre del servicio

        Retorna:
            Dict con:
                - remaining: requests restantes
                - window_seconds: duración de la ventana
                - max_requests: límite máximo de la ventana
        """
        with self._lock:
            timestamps = self._timestamps.get(service, [])
            limit = self.RATE_LIMITS.get(service)

            if not limit:
                return {"remaining": 999}

            recent = [t for t in timestamps if t > time.time() - limit.window_seconds]

            return {
                "remaining": max(0, limit.max_requests - len(recent)),
                "window_seconds": limit.window_seconds,
                "max_requests": limit.max_requests,
            }

    def wait_if_needed(self, service: str, max_wait: float = 60.0) -> None:
        """
        Esperar si se excedió el límite de tasa del servicio.

        Si el servicio está en su límite de tasa, espera el tiempo
        necesario hasta que haya espacio disponible.

        Parámetros:
            service: Nombre del servicio
            max_wait: Tiempo máximo de espera en segundos
        """
        with self._lock:
            timestamps = self._timestamps.get(service, [])
            limit = self.RATE_LIMITS.get(service)

            if not limit:
                return

            wait_time = limit.get_retry_after(timestamps)
            if wait_time > 0:
                logger.info(f"Rate limit for {service}, waiting {wait_time:.1f}s")
                wait_time = min(wait_time, max_wait)
                time.sleep(wait_time)

    def get_all_limits(self) -> Dict[str, Dict[str, int]]:
        """
        Obtener los límites de todos los servicios.

        Retorna:
            Dict con el estado de límites de cada servicio
        """
        with self._lock:
            result = {}
            for service in self.RATE_LIMITS:
                result[service] = self.check_remaining(service)
            return result

    def reset(self, service: Optional[str] = None) -> None:
        """
        Resetear el tracking de rate limits.

        Parámetros:
            service: Nombre del servicio a resetear (None = todos)
        """
        with self._lock:
            if service:
                self._timestamps.pop(service, None)
            else:
                self._timestamps.clear()


# Instancia global (singleton)
_rate_limit_tracker: Optional[RateLimitTracker] = None


def get_rate_limit_tracker() -> RateLimitTracker:
    """
    Obtener el tracker de límites de tasa (singleton).

    Patrón singleton: se crea una sola instancia y se reutiliza.
    Usado por llm_client.py para aplicar rate limiting.

    Retorna:
        Instancia de RateLimitTracker
    """
    global _rate_limit_tracker
    if _rate_limit_tracker is None:
        _rate_limit_tracker = RateLimitTracker()
    return _rate_limit_tracker
