"""
Conexión a la base de datos con SQLAlchemy y psycopg3.

psycopg3 es el driver postgreSQL para Python.
La versión "binary" ya viene compilada, no necesita C compiler en Windows.

¿Por qué psycopg (sync) en vez de asyncpg?
- asyncpg requiere compilación C (no funciona en Windows sin Visual Studio)
- psycopg3 sí funciona con pip install normal
- La diferencia es mínima para este proyecto (no tenemos millones de requests/segundo)

¿Qué cambia en la práctica?
- Usamos sessionmaker (sync) en vez de async_sessionmaker
- Usamos session.execute() (sync) en vez de await session.execute()
- Todo lo demás es igual: model, query, CRUD
"""

from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from ai_platform.core.config import get_settings

settings = get_settings()

# Crear el motor de SQLAlchemy
# StaticPool: mantiene una conexión única para desarrollo (más simple)
# En producción, usar QueuePool para conexiones reales
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
)

# Crear el factory de sesiones
# Una Session es un "contexto de trabajo" con la BD
session_factory = sessionmaker(
    engine,
    expire_on_commit=False
)


# Clase base para todos los modelos de la BD
class Base(DeclarativeBase):
    """
    Base de SQLAlchemy para todos los modelos.
    
    Cada tabla es una clase que hereda de Base:
    
        class User(Base):
            __tablename__ = "users"
            id = Column(PG_UUID, primary_key=True)
            name = Column(String(255))
    """
    pass


def get_db_session() -> Generator[Session, None, None]:
    """
    Dependency de FastAPI para obtener una sesión de base de datos.
    
    FastAPI la inyecta automáticamente en los endpoints usando Depends().
    Se encarga de crear la session al inicio del request
    y cerrarla al final automáticamente.
    
    Uso en endpoints:
        @app.get("/users/{user_id}")
        def get_user(user_id: UUID, db: Session = Depends(get_db_session)):
            user = db.get(User, user_id)
            return user
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def make_session() -> Generator[Session, None, None]:
    """
    Crear manualmente una sesión de BD (para usar fuera de FastAPI).
    
    Útil para módulos que no son endpoints:
        with make_session() as db:
            db.execute(...)
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
