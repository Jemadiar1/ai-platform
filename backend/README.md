# Backend de NeuralCrew Labs

Backend de la plataforma de marketing impulsada por IA.

## Tecnologías

- **FastAPI** - Framework de API de alto rendimiento
- **SQLAlchemy 2.0** - ORM asíncrono para PostgreSQL
- **Pydantic V2** - Validación de datos y settings
- **Celery** - Workers asíncronos con Redis
- **Alembic** - Migraciones de base de datos

## Instalación

```bash
# Instalar Poetry si no lo tienes
pip install poetry

# Instalar dependencias
cd backend
poetry install

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales

# Ejecutar migraciones
poetry run alembic upgrade head

# Iniciar servidor de desarrollo
poetry run task run

# Ejecutar workers de Celery (en otra terminal)
poetry run celery -A ai_platform.workers.task_runner worker --loglevel=info --concurrency=4

# Ejecutar tests
poetry run task test

# Ejecutar linter
poetry run task lint

# Ejecutar type checker
poetry run task mypy
```

## Estructura

```
backend/
├── src/ai_platform/          # Código principal
│   ├── main.py               # Entry point (FastAPI app)
│   ├── core/                 # Configuración, seguridad, eventos
│   ├── middleware/           # Middleware (tenant, auth, logging)
│   ├── api/                  # Endpoints de la API
│   ├── services/             # Servicios de negocio
│   ├── modules/              # Módulos de IA (ai-connect, ai-social, etc.)
│   ├── workers/              # Workers Celery
│   ├── models/               # Modelos SQLAlchemy
│   ├── schemas/              # Schemas Pydantic
│   └── shared/               # Tipos y constantes compartidas
├── migrations/               # Migraciones Alembic
├── tests/                    # Tests pytest
└── pyproject.toml            # Dependencias Poetry
```

## API Documentation

- Swagger UI: http://localhost:4000/docs
- ReDoc: http://localhost:4000/redoc
