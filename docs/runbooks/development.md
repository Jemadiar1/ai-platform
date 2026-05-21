# Development Runbook

Estado del documento: 2026-05-20

## Prerrequisitos

- Python 3.11
- Poetry 1.8+
- Node.js compatible con Next.js 14
- pnpm 10.7.0
- Docker Desktop o Docker Engine con Compose

## Variables De Entorno

Hay dos archivos de referencia:

- `.env.example`: variables generales de desarrollo.
- `infra/docker/.env.example`: variables para despliegue productivo con Docker Compose y Nginx.

Para desarrollo local, crea `.env` en la raíz o exporta las variables antes de correr el backend. La aplicación FastAPI lee `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, credenciales de proveedores y llaves de canales desde `ai_platform.core.config`.

Notas importantes:

- `SECRET_KEY` no puede quedarse en el valor placeholder en producción.
- `WHATSAPP_APP_SECRET` se usa en el canal WhatsApp, pero todavía no está declarado en `Settings`.
- `CORS_ORIGINS` aparece en Compose productivo, pero FastAPI todavía usa una lista hardcodeada de localhost.

## Infraestructura Local

Levantar PostgreSQL y Redis:

```powershell
docker compose -f infra/compose/docker-compose.dev.yml up -d
```

Servicios locales:

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- Base por defecto: `ai_platform`
- Usuario/password por defecto: `postgres` / `postgres`

Detener infraestructura:

```powershell
docker compose -f infra/compose/docker-compose.dev.yml down
```

## Backend Python

Instalar dependencias:

```powershell
cd backend
poetry install
```

Arrancar FastAPI:

```powershell
poetry run task run
```

La API queda en:

- `http://localhost:4000/api/v1/health`
- `http://localhost:4000/api/v1/ping`
- `http://localhost:4000/docs`
- `http://localhost:4000/redoc`

Crear tablas rápido para desarrollo:

```powershell
poetry run python create_tables.py
```

Listar tablas:

```powershell
poetry run python create_tables.py --list
```

Eliminar tablas locales:

```powershell
poetry run python create_tables.py --drop
```

Advertencia: `create_tables.py --drop` elimina tablas de la base configurada por `DATABASE_URL`.

## Migraciones

El repo tiene dos árboles Alembic:

- `backend/alembic` usado por `backend/migrate.py` y `backend/alembic.ini`.
- `backend/migrations/alembic` copiado por `infra/docker/Dockerfile`.

Hasta resolver esa duplicación, usa `create_tables.py` para setups locales rápidos y evita crear nuevas migraciones sin decidir primero la ruta canónica.

Comandos existentes:

```powershell
cd backend
poetry run python migrate.py current
poetry run python migrate.py history
poetry run python migrate.py upgrade head
```

## Worker Celery

El worker Python existe en `backend/src/ai_platform/workers/task_runner.py`.

Comando base:

```powershell
cd backend
poetry run celery -A ai_platform.workers.task_runner.celery_app worker --loglevel=info
```

Limitaciones actuales:

- El worker usa Redis hardcodeado en `redis://localhost:6379/1` y backend `redis://localhost:6379/2`.
- El endpoint `POST /api/v1/tasks` crea la tarea, pero todavía no publica en Redis/Celery.
- El registro de `usage_event` tiene TODO para resolver `tenant_id` real.

## Workspace TypeScript

Instalar dependencias del monorepo:

```powershell
pnpm install
```

Ejecutar tareas del workspace:

```powershell
pnpm dev
pnpm build
pnpm lint
pnpm test
pnpm typecheck
```

Apps y servicios actuales:

- `apps/dashboard`: prototipo Next.js.
- `apps/admin`: placeholder Next.js.
- `apps/website`: placeholder Next.js.
- `services/api-gateway`: Fastify mínimo con `/health` y `/api/v1/ping`.
- `workers/scheduler`: worker TS mínimo.
- `workers/task-runner`: worker TS mínimo.

Nota: el backend productivo real no pasa actualmente por `services/api-gateway`; Nginx enruta al backend Python.

## Pruebas Y Calidad

Backend:

```powershell
cd backend
poetry run ruff check src
poetry run ruff format --check src
poetry run pytest tests/ -v --tb=short --ignore-glob="**/test_modules/*"
```

CI activo en GitHub:

- `.github/workflows/ci.yml`
- Ruff lint/format
- Pytest con PostgreSQL
- Typecheck deshabilitado para legacy
- Build y push de imagen GHCR en `main`

Typecheck local opcional:

```powershell
cd backend
poetry run mypy src
```

El archivo `infra/ci/github-actions/ci.yml` contiene una validación TypeScript histórica, pero no es el workflow activo de GitHub.

## Docker Producción

Assets principales:

- `infra/docker/Dockerfile`
- `infra/docker/docker-compose.prod.yml`
- `infra/docker/nginx/nginx.conf.template`
- `infra/docker/.env.example`

Validar compose:

```powershell
docker compose --env-file infra/docker/.env.example -f infra/docker/docker-compose.prod.yml config --quiet
```

Topología productiva esperada:

- Nginx publica `80` y `443`.
- El backend Python expone `4000` solo dentro de la red Docker.
- PostgreSQL y Redis no se publican abiertamente.

Advertencia: algunos scripts de despliegue todavía prueban `http://localhost:4000` o `http://<VPS>:4000`; con el compose productivo actual, el health público debe probarse vía Nginx.

## Checklist Antes De Subir Cambios

1. `git status --short --branch`
2. `git diff --check`
3. Backend: `poetry run ruff check src`
4. Backend: `poetry run pytest tests/ -v --tb=short --ignore-glob="**/test_modules/*"`
5. Si tocaste Docker: validar `docker compose ... config --quiet`
6. Si tocaste Nginx: validar la plantilla con `nginx -t` dentro del contenedor o entorno equivalente

## Brechas Conocidas Que Afectan Desarrollo

- `channel_mappings` está referenciado por webhooks, pero no está en el modelo SQLAlchemy principal ni en la ruta de migración copiada por Docker.
- `Odin._invoke_module()` todavía no ejecuta handlers reales.
- El dashboard intenta leer `/api/v1/usage`, pero la API no expone esa ruta.
- `WHATSAPP_APP_SECRET` falta en `Settings`.
- Prometheus apunta a `api-gateway:4000`, que no representa el despliegue actual.
