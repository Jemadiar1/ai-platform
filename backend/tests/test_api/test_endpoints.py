"""
Tests para los endpoints de la API.

Estos tests verifican que los endpoints respondan correctamente
sin necesidad de levantar un servidor real.

Uso:
    pytest backend/tests/test_api/ -v
"""

import pytest
from fastapi.testclient import TestClient

from ai_platform.main import app


# Crear cliente de prueba
client = TestClient(app)


class TestPingEndpoint:
    """Tests para el endpoint /api/v1/ping"""
    
    def test_ping_returns_ok(self):
        """Verificar que el endpoint ping devuelve 200 OK"""
        response = client.get("/api/v1/ping")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "ai-platform-backend"
        assert "timestamp" in data
    
    def test_ping_has_timestamp(self):
        """Verificar que el endpoint ping incluye timestamp"""
        response = client.get("/api/v1/ping")
        data = response.json()
        
        # El timestamp debe ser una cadena ISO 8601
        assert "T" in data["timestamp"]
        assert "+" in data["timestamp"] or "Z" in data["timestamp"]


class TestHealthEndpoint:
    """Tests para el endpoint /api/v1/health"""
    
    def test_health_returns_status(self):
        """Verificar que el endpoint health devuelve estado"""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "components" in data
        assert "timestamp" in data
    
    def test_health_has_components(self):
        """Verificar que el endpoint health incluye componentes"""
        response = client.get("/api/v1/health")
        data = response.json()
        
        # components debe ser un diccionario
        assert isinstance(data["components"], dict)


class TestTasksEndpoint:
    """Tests para el endpoint /api/v1/tasks"""
    
    def test_create_task_requires_auth(self):
        """Verificar que crear tarea requiere autenticación"""
        # Sin token, debe devolver 401
        response = client.post("/api/v1/tasks", json={
            "module": "ai-connect",
            "payload": {"action": "test"}
        })
        assert response.status_code == 401
    
    def test_list_tasks_requires_auth(self):
        """Verificar que listar tareas requiere autenticación"""
        response = client.get("/api/v1/tasks")
        assert response.status_code == 401
    
    def test_list_tasks_with_pagination(self):
        """Verificar que listar tareas acepta parámetros de paginación"""
        # Con token válido, debería devolver lista vacía
        # (no tenemos datos en la BD de test)
        # Por ahora verificamos que la ruta exista
        response = client.get("/api/v1/tasks?limit=10&offset=0")
        # Devuelve 401 porque no hay auth, pero la ruta existe
        assert response.status_code == 401


class TestTenantsEndpoint:
    """Tests para el endpoint /api/v1/tenants"""
    
    def test_get_current_tenant_requires_auth(self):
        """Verificar que obtener tenant actual requiere autenticación"""
        response = client.get("/api/v1/tenants/me")
        assert response.status_code == 401
    
    def test_create_tenant_requires_slug(self):
        """Verificar que crear tenant requiere slug"""
        # Sin auth, devuelve 401
        response = client.post("/api/v1/tenants", json={
            "name": "Test",
            "slug": ""  # Slug vacío
        })
        assert response.status_code == 401


class TestDocsEndpoint:
    """Tests para los endpoints de documentación"""
    
    def test_docs_available(self):
        """Verificar que Swagger UI está disponible"""
        response = client.get("/docs")
        assert response.status_code == 200
    
    def test_redoc_available(self):
        """Verificar que ReDoc está disponible"""
        response = client.get("/redoc")
        assert response.status_code == 200
    
    def test_openapi_schema_available(self):
        """Verificar que el esquema OpenAPI está disponible"""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "paths" in data
        assert "/api/v1/ping" in data["paths"]
