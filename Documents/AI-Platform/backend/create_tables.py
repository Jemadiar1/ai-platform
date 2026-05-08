"""
Script para crear tablas directamente desde modelos SQLAlchemy.

Útil para setup rápido en desarrollo sin Alembic.

Uso:
    python create_tables.py        # Crear todas las tablas
    python create_tables.py --drop # Eliminar todas las tablas

Configuración:
    Lee DATABASE_URL desde variable de entorno o desde .env
"""

import os
import sys

# Agregar src al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import argparse
from sqlalchemy import inspect

from ai_platform.database import engine, Base
from ai_platform.models.db import (
    Tenant,
    User,
    Task,
    UsageEvent,
    AgentMemory,
    Session,
    Message,
)


def create_tables():
    """Crear todas las tablas desde los modelos SQLAlchemy."""
    print("Creando tablas de base de datos...")
    Base.metadata.create_all(engine)
    print("Tablas creadas exitosamente.")

    # Listar tablas creadas
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\nTablas en la base de datos:")
    for table in sorted(tables):
        print(f"  - {table}")


def drop_tables():
    """Eliminar todas las tablas."""
    print("ADVERTENCIA: Eliminando todas las tablas...")
    Base.metadata.drop_all(engine)
    print("Todas las tablas eliminadas.")


def main():
    parser = argparse.ArgumentParser(description="Gestionar tablas de base de datos")
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Eliminar todas las tablas",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Listar tablas existentes",
    )

    args = parser.parse_args()

    if args.drop:
        drop_tables()
    elif args.list:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"Tablas existentes ({len(tables)}):")
        for table in sorted(tables):
            print(f"  - {table}")
    else:
        create_tables()


if __name__ == "__main__":
    main()
