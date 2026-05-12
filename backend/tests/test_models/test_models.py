"""
Tests para los modelos de SQLAlchemy.

Estos tests verifican que los modelos de base de datos funcionan correctamente
usando una base de datos SQLite en memoria (no afecta la BD real).

Uso:
    pytest backend/tests/test_models/ -v
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_platform.database import Base
from ai_platform.models.db import Tenant, User, Task, UsageEvent, AgentMemory
from uuid import uuid4


@pytest.fixture
def db_session():
    """Crear una sesión de base de datos de prueba con SQLite en memoria"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


class TestTenantModel:
    """Tests para el modelo Tenant"""
    
    def test_create_tenant(self, db_session):
        """Verificar que se puede crear un tenant"""
        tenant = Tenant(
            name="Test Company",
            slug="test-company",
            plan="starter"
        )
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)
        
        assert tenant.id is not None
        assert tenant.name == "Test Company"
        assert tenant.slug == "test-company"
        assert tenant.plan == "starter"
        assert tenant.is_active == True
    
    def test_tenant_slug_unique(self, db_session):
        """Verificar que los slugs son únicos"""
        tenant1 = Tenant(name="Company 1", slug="unique-slug")
        tenant2 = Tenant(name="Company 2", slug="unique-slug")
        
        db_session.add(tenant1)
        db_session.commit()
        
        tenant2.name = "Company 2"
        tenant2.slug = "unique-slug"  # Mismo slug
        db_session.add(tenant2)
        
        # Debería fallar por unique constraint
        with pytest.raises(Exception):
            db_session.commit()


class TestUserModel:
    """Tests para el modelo User"""
    
    def test_create_user(self, db_session):
        """Verificar que se puede crear un usuario"""
        tenant = Tenant(name="Test", slug="test")
        db_session.add(tenant)
        db_session.commit()
        
        user = User(
            tenant_id=tenant.id,
            clerk_user_id="clerk_123",
            email="test@example.com",
            name="Test User",
            role="admin"
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        
        assert user.id is not None
        assert user.tenant_id == tenant.id
        assert user.email == "test@example.com"
        assert user.role == "admin"


class TestTaskModel:
    """Tests para el modelo Task"""
    
    def test_create_task(self, db_session):
        """Verificar que se puede crear una tarea"""
        tenant = Tenant(name="Test", slug="test")
        db_session.add(tenant)
        db_session.commit()
        
        task = Task(
            tenant_id=tenant.id,
            module="ai-connect",
            status="pending",
            payload={"action": "send_whatsapp", "to": "+1234567890"}
        )
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)
        
        assert task.id is not None
        assert task.module == "ai-connect"
        assert task.status == "pending"
        assert task.retry_count == 0
        assert task.priority == 0
    
    def test_task_status_transitions(self, db_session):
        """Verificar que una tarea puede cambiar de estado"""
        tenant = Tenant(name="Test", slug="test")
        db_session.add(tenant)
        db_session.commit()
        
        task = Task(
            tenant_id=tenant.id,
            module="ai-social",
            status="pending",
            payload={"action": "post"}
        )
        db_session.add(task)
        db_session.commit()
        
        # Cambiar a running
        task.status = "running"
        db_session.commit()
        
        # Cambiar a completed
        task.status = "completed"
        task.result = {"post_id": "123456"}
        db_session.commit()
        
        db_session.refresh(task)
        assert task.status == "completed"
        assert task.result["post_id"] == "123456"


class TestUsageEventModel:
    """Tests para el modelo UsageEvent"""
    
    def test_create_usage_event(self, db_session):
        """Verificar que se puede crear un evento de uso"""
        tenant = Tenant(name="Test", slug="test")
        db_session.add(tenant)
        db_session.commit()
        
        task = Task(
            tenant_id=tenant.id,
            module="ai-connect",
            status="completed"
        )
        db_session.add(task)
        db_session.commit()
        
        usage = UsageEvent(
            tenant_id=tenant.id,
            task_id=task.id,
            module="ai-connect",
            event_type="task_execution",
            tokens_used=1500,
            cost_usd=0.05
        )
        db_session.add(usage)
        db_session.commit()
        db_session.refresh(usage)
        
        assert usage.id is not None
        assert usage.tokens_used == 1500
        assert usage.cost_usd == 0.05


class TestAgentMemoryModel:
    """Tests para el modelo AgentMemory"""
    
    def test_create_memory(self, db_session):
        """Verificar que se puede crear memoria de agente"""
        tenant = Tenant(name="Test", slug="test")
        db_session.add(tenant)
        db_session.commit()
        
        memory = AgentMemory(
            tenant_id=tenant.id,
            agent_id="ai-connect",
            type="short_term",
            content="Usuario preguntó sobre precios"
        )
        db_session.add(memory)
        db_session.commit()
        db_session.refresh(memory)
        
        assert memory.id is not None
        assert memory.agent_id == "ai-connect"
        assert memory.type == "short_term"
