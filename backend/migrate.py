"""
Script de línea de comandos para ejecutar migraciones de Alembic.

Uso:
    python migrate.py upgrade        # Ejecutar migraciones pendientes
    python migrate.py upgrade head    # Ir a la última versión
    python migrate.py upgrade 1a2b3c  # Ir a versión específica
    python migrate.py downgrade -1    # Revertir última migración
    python migrate.py downgrade base  # Revertir todas
    python migrate.py current         # Ver versión actual
    python migrate.py history         # Ver historial de migraciones

Configuración:
    Lee DATABASE_URL desde variable de entorno o desde .env
"""

import argparse
import os
import sys

# Agregar src al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from alembic.command import upgrade, downgrade, current, history, revision
from alembic.config import Config


def get_alembic_config():
    """Obtener configuración de Alembic desde backend/alembic.ini."""
    alembic_ini_path = os.path.join(os.path.dirname(__file__), "alembic.ini")
    return Config(alembic_ini_path)


def main():
    parser = argparse.ArgumentParser(description="Gestionar migraciones de base de datos")
    parser.add_argument(
        "command",
        choices=["upgrade", "downgrade", "current", "history"],
        help="Comando de Alembic",
    )
    parser.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="Versión de migración (default: head para upgrade, -1 para downgrade)",
    )

    args = parser.parse_args()

    config = get_alembic_config()

    if args.command == "upgrade":
        upgrade(config, args.revision)
        print(f"Migración exitosa: {args.revision}")

    elif args.command == "downgrade":
        downgrade(config, args.revision)
        print(f"Rollback exitoso: {args.revision}")

    elif args.command == "current":
        current(config, verbose=True)

    elif args.command == "history":
        history(config, verbose=True)


if __name__ == "__main__":
    main()
