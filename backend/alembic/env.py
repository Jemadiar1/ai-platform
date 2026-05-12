"""
Entorno de Alembic para AI Platform.

Lee la URL de la base de datos desde la configuración de la app
y ejecuta las migraciones.
"""

import logging
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Agregar src al path para imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_platform.database import Base
from ai_platform.models.db import (
    Tenant,
    User,
    Task,
    UsageEvent,
    AgentMemory,
    Session,
    Message,
)

# Configurar logging
logger = logging.getLogger("alembic.env")

config = context.config

# Leer DATABASE_URL desde variable de entorno o settings
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/ai_platform",
)

# Sobrescribir la URL en el config de alembic
target_db_url = DATABASE_URL
config.set_main_option("sqlalchemy.url", target_db_url)

# Importar Base para autogeneración
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Ejecutar migraciones en modo 'offline'.
    
    El contexto SQL se obtiene directamente de la URL, sin crear
    realmente una conexión a la base de datos. Útil para generar
    scripts SQL sin conectar.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Ejecutar migraciones en modo 'online'.
    
    Crea una conexión real a la base de datos y ejecuta
    las migraciones.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    logger.info("Ejecutando migraciones offline")
    run_migrations_offline()
else:
    logger.info("Ejecutando migraciones online")
    run_migrations_online()
