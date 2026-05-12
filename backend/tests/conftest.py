"""
Fixtures de pytest para el backend.

Este módulo define fixtures reutilizables para los tests.
Los fixtures crean un ambiente de test aislado sin afectar la BD de desarrollo.

Uso:
    import pytest
    
    def test_endpoint(client):
        response = client.get("/api/v1/ping")
        assert response.status_code == 200

    def test_db_query(db_session):
        tenant = Tenant(name="Test")
        db_session.add(tenant)
        db_session.commit()
        assert tenant.id is not None

"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ai_platform.database import Base, session_factory
from ai_platform.main import app


@pytest.fixture
def client():
    """
    Cliente de prueba de FastAPI.
    
    Crea un cliente TestClient que envía requests HTTP al app de FastAPI
    sin necesidad de levantar un servidor real.
    
    Es como hacer curl pero desde Python, sin networking real.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session():
    """
    Sesión de base de datos de pruebas.
    
    Crea una BD en memoria SQLite separada de la BD real.
    Esto permite hacer tests reales sin afectar los datos de producción.
    
    Flujo:
    1. Crear BD SQLite en memoria
    2. Crear todas las tablas (metadata.create_all)
    3. Crear una session
    4. Ejecutar el test
    5. Descartar todos los cambios (rollback)
    6. Eliminar la BD en memoria
    """
    # Crear engine con SQLite en memoria
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    
    # Crear tablas en la BD de memoria
    Base.metadata.create_all(bind=engine)
    
    # Crear session
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def sample_tenant(db_session):
    """
    Fixture que crea un tenant de ejemplo para los tests.
    
    Uso:
        def test_with_tenant(db_session, sample_tenant):
            assert sample_tenant.name == "Test Tenant"
            assert sample_tenant.plan == "starter"
    """
    from ai_platform.models.db import Tenant
    from uuid import uuid4
    
    tenant = Tenant(
        name="Test Tenant",
        slug="test-tenant",
        plan="starter",
        clerk_user_id=str(uuid4())
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


@pytest.fixture
def sample_task(db_session, sample_tenant):
    """
    Fixture que crea una tarea de ejemplo para los tests.
    
    Usa sample_tenant para asociar la tarea al tenant correcto.
    
    Uso:
        def test_with_task(db_session, sample_task):
            assert sample_task.status == "pending"
            assert sample_task.module == "ai-connect"
    """
    from ai_platform.models.db import Task
    
    task = Task(
        tenant_id=sample_tenant.id,
        module="ai-connect",
        status="pending",
        payload={"action": "test", "to": "+1234567890"},
        priority=0
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


@pytest.fixture
def valid_password():
    """Contraseña válida de prueba."""
    return "TestPass123!"


@pytest.fixture
def hashed_password():
    """Contraseña hasheada de prueba."""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash("TestPass123!")


@pytest.fixture
def test_tenant_id():
    """UUID de tenant para pruebas."""
    from uuid import uuid4
    return str(uuid4())


@pytest.fixture
def sample_safe_text():
    """Texto seguro para pruebas de escaneo."""
    return "Este es un mensaje seguro y normal sin contenido malicioso"


@pytest.fixture
def sample_injection_text():
    """Texto con intento de inyección SQL."""
    return "Hola; DROP TABLE users; --"


@pytest.fixture
def sample_bidi_text():
    """Texto con caracteres bidireccionales."""
    return "Hola\u202Emundo\u202C"


@pytest.fixture
def sample_null_bytes():
    """Texto con bytes nulos incrustados."""
    return "Hola\x00mundo\x00"
