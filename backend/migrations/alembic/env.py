"""
Configuración de Alembic para migraciones de base de datos.

Alembic es el sistema de migraciones para SQLAlchemy.
Permite versionar cambios en la estructura de la base de datos.

¿Qué es una migración?
- Es un script que modifica la estructura de la BD
- Ejemplo: agregar columna, cambiar tipo, crear tabla
- Cada migración tiene un ID único (ej: "1a2b3c4d5e6f")
- Las migraciones se ejecutan en orden cronológico

Flujo de trabajo:
1. Modificas los modelos en models/db.py
2. Ejecutas: alembic revision --autogenerate -m "descripción"
3. Revisas el script generado en migrations/alembic/versions/
4. Ejecutas: alembic upgrade head

¿Por qué Alembic?
- Version control para la estructura de la BD
- Fácil de revertir cambios (downgrade)
- Funciona con cualquier base de datos soportada por SQLAlchemy
- Genera scripts automáticamente (autogenerate)

"""

import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Importar los modelos de la aplicación
# Esto es necesario para que Alembic detecte cambios en las tablas
sys.path.insert(0, "src")
from ai_platform.database import Base
from ai_platform.models.db import Tenant, User, Task, UsageEvent, AgentMemory  # noqa: F401

# Configuración de logging
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata para autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Ejecutar migraciones en modo "offline".
    
    Modo offline: genera SQL directamente sin conectar a la BD.
    Útil para revisar el SQL antes de ejecutarlo.
    
    Uso:
        alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Ejecutar migraciones en modo "online".
    
    Modo online: conecta a la BD real y aplica los cambios.
    Este es el modo normal de operación.
    
    Uso:
        alembic upgrade head
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
