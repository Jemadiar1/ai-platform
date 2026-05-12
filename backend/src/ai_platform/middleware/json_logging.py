"""
Logging estructurado con JSONFormatter.

Para producción, los logs deben ser JSON para que puedan ser ingesticos
por herramientas de observabilidad como:
- Prometheus/Grafana
- ELK Stack (Elasticsearch, Logstash, Kibana)
- Datadog
- New Relic

Este módulo configura el logging para que:
1. En desarrollo: logs en texto plano legible
2. En producción: logs en JSON estructurado

Uso:
    from ai_platform.middleware.logging import setup_production_logging
    setup_production_logging()
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    """
    Formateador que convierte logs de Python a JSON.

    Cada evento de log se convierte en un JSON con:
    - timestamp: cuando ocurrió el evento
    - level: nivel del log (INFO, WARNING, ERROR)
    - logger: nombre del logger
    - message: mensaje del log
    - func_name: función que generó el log
    - line_number: línea del código
    - extra: cualquier campo adicional pasado al log

    Ejemplo de output:
    {
        "timestamp": "2026-05-07T10:00:00Z",
        "level": "INFO",
        "logger": "ai_platform",
        "message": "request_start",
        "func_name": "dispatch",
        "line_number": 86,
        "method": "GET",
        "path": "/api/v1/tasks",
        "status_code": 200,
        "duration_ms": 45.2
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Convertir un log record a JSON.

        Parámetros:
            record: Objeto LogRecord de Python logging

        Retorna:
            String JSON con los datos del log
        """
        # Crear dict base con campos estándar
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "func_name": record.funcName,
            "line_number": record.lineno,
        }

        # Añadir campos extra si existen
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        # Si hay excepciones, añadirlas
        if record.exc_info and record.exc_info[0] is not None:
            log_data["exception"] = self.formatException(record.exc_info)

        # Convertir a JSON
        return json.dumps(log_data, ensure_ascii=False)


def setup_production_logging(log_level: str = "INFO") -> None:
    """
    Configurar logging para producción (JSON).

    Esta función debe llamarse al iniciar la aplicación en producción.
    Configura el root logger para que envíe logs a stdout en formato JSON.

    Parámetros:
        log_level: Nivel mínimo de log (DEBUG, INFO, WARNING, ERROR)

    Uso:
        # En main.py, antes de crear la app:
        from ai_platform.middleware.logging import setup_production_logging
        setup_production_logging("INFO")
    """
    # Configurar handler con JSONFormatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    # Configurar root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Eliminar handlers existentes para evitar duplicados
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Desactivar loggers de terceros que generan mucho ruido
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def setup_development_logging(log_level: str = "INFO") -> None:
    """
    Configurar logging para desarrollo (texto plano).

    Esta función debe llamarse al iniciar la aplicación en desarrollo.
    Configura el root logger para que envíe logs a stderr en texto plano.

    Parámetros:
        log_level: Nivel mínimo de log (DEBUG, INFO, WARNING, ERROR)

    Uso:
        # En main.py, antes de crear la app:
        from ai_platform.middleware.logging import setup_development_logging
        setup_development_logging("DEBUG")
    """
    # Configurar handler con formato de texto plano
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )

    # Configurar root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Eliminar handlers existentes para evitar duplicados
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
