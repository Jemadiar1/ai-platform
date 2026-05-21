# Reporte De Estado Actual Del Repositorio

Fecha: 2026-05-20
Referencia de revisión local: `61978ae`

## Alcance

Este reporte resume el estado real del repositorio después de revisar estructura, backend, frontend, paquetes compartidos, servicios, workers, infraestructura, observabilidad, migraciones y documentación.

No reemplaza el reporte histórico `2026-04-16-architecture-refactor-report.md`; lo complementa con el estado actual del código.

## Resumen Ejecutivo

La base funcional principal está en el backend Python:

- FastAPI expone la API real.
- Odin coordina decisión, contexto, memoria, modelos y fallback.
- SQLAlchemy define las entidades principales.
- PostgreSQL y Redis son las dependencias de datos.
- Docker producción ejecuta el backend Python detrás de Nginx.

El workspace TypeScript sigue siendo útil como estructura de producto y futuro crecimiento, pero muchas piezas son scaffolds:

- `apps/dashboard` es un prototipo.
- `apps/admin` y `apps/website` son placeholders.
- `services/api-gateway` es un Fastify mínimo.
- `services/orchestrator` no reemplaza al Odin Python.
- `workers/scheduler` y `workers/task-runner` TS solo devuelven estado listo.

## Inventario Por Área

### Raíz Del Repositorio

- `package.json`: scripts Turborepo para build, dev, lint, test y typecheck.
- `pnpm-workspace.yaml`: workspaces `apps/*`, `services/*`, `workers/*`, `packages/*`.
- `turbo.json`: pipeline básica con build, dev persistente, lint, test y typecheck.
- `tsconfig.base.json`: configuración TypeScript estricta y paths para paquetes compartidos.

### Backend

Ubicación: `backend/src/ai_platform`

Componentes relevantes:

- `main.py`: app FastAPI, routers, CORS, middleware de logging y startup de cron.
- `api/v1`: ping, health, tenants, tasks, Odin y webhooks.
- `core/config.py`: settings Pydantic.
- `database.py`: engine y sesiones SQLAlchemy.
- `models/db.py`: modelos principales.
- `models/channel_mapping.py`: helpers SQL para `channel_mappings`.
- `orchestrator`: Odin, LLM client, memoria, sesiones, pricing, rate limits, plugins, subagentes, skills y observabilidad.
- `modules`: handlers Python para dominios `ai_*`.
- `channels`: Telegram, WhatsApp y Discord.
- `workers/task_runner.py`: Celery worker Python.

### Endpoints Implementados

- `GET /api/v1/ping`
- `GET /api/v1/health`
- `POST /api/v1/Odin/decide`
- `POST /api/v1/tasks`
- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `PATCH /api/v1/tasks/{task_id}`
- `DELETE /api/v1/tasks/{task_id}`
- `GET /api/v1/tenants/me`
- `POST /api/v1/tenants`
- `POST /api/v1/webhooks/clerk`
- `POST /api/v1/webhooks/stripe`
- `POST /api/v1/webhooks/telegram`
- `POST /api/v1/webhooks/whatsapp`
- `POST /api/v1/webhooks/discord`

Endpoint esperado por dashboard pero no implementado:

- `GET /api/v1/usage`

### Modelos Persistentes

Modelos SQLAlchemy actuales:

- `Tenant`
- `User`
- `Task`
- `UsageEvent`
- `AgentMemory`
- `Session`
- `Message`

Tabla referenciada por SQL manual:

- `channel_mappings`

La tabla `channel_mappings` requiere reconciliación porque aparece en código de webhooks y en una migración alternativa, pero no está en el modelo principal ni en el árbol de migraciones copiado por Docker.

### Migraciones

Existen dos árboles Alembic:

- `backend/alembic`
- `backend/migrations/alembic`

Observación:

- `backend/migrate.py` apunta a `backend/alembic.ini`, cuyo `script_location` es `alembic`.
- `infra/docker/Dockerfile` copia `backend/migrations`.
- `backend/alembic/versions/001_initial_schema.py` contiene `channel_mappings`.
- `backend/migrations/alembic/versions/001_initial_schema.py` no contiene `channel_mappings`.

Esto es una brecha prioritaria porque afecta canales, webhooks y despliegue.

### Orquestación

Odin implementa:

- detección inicial de prompt injection;
- administración de sesión;
- memoria y knowledge base;
- selección de proveedor/modelo;
- fallback rule-based;
- cálculo de parámetros;
- descomposición de tareas;
- hooks de plugins;
- observabilidad y trayectoria.

Brecha principal:

- `_invoke_module()` devuelve placeholder. El flujo directo de Odin no ejecuta todavía handlers reales.

### Módulos

Módulos Python bajo `backend/src/ai_platform/modules`:

- `ai_connect`: validaciones y stubs con más lógica.
- `ai_web`: stub.
- `ai_content`: stub.
- `ai_social`: stub.
- `ai_leads`: stub.
- `ai_ads`: stub.
- `ai_analytics`: stub.

Scaffolds bajo `modules/ai-*`:

- mantienen estructura de dominio, prompts, contracts, tools y tests.
- no son el runtime principal actual.

### Canales Y Webhooks

Canales presentes:

- Telegram
- WhatsApp
- Discord
- Clerk
- Stripe

Hallazgos:

- WhatsApp verifica firma con `WHATSAPP_APP_SECRET`, pero ese setting falta.
- El handler WhatsApp contiene lógica de challenge GET dentro de una ruta `POST`, por lo que esa rama no queda expuesta como GET.
- La ejecución dinámica desde webhooks espera funciones `execute` o `execute_async` a nivel módulo, mientras los handlers reales están modelados como clases `Handler`.

### Frontend

Apps:

- `apps/dashboard`: prototipo visual que consulta `http://localhost:4000/api/v1/tasks?limit=5` y `/api/v1/usage`.
- `apps/admin`: placeholder.
- `apps/website`: placeholder.

Riesgos visibles:

- El dashboard depende de `/api/v1/usage`, que no existe.
- La app dashboard debe revisarse antes de considerarla lista para build productivo.

### Servicios Y Workers TypeScript

- `services/api-gateway`: Fastify mínimo con `/health` y `/api/v1/ping`.
- `services/orchestrator`: configuración y Dockerfile, sin runtime equivalente al orquestador Python.
- `workers/scheduler`: worker mínimo.
- `workers/task-runner`: worker mínimo.

Estos componentes no son hoy el camino productivo principal.

### Infraestructura

Desarrollo:

- `infra/compose/docker-compose.dev.yml` levanta PostgreSQL y Redis.

Producción:

- `infra/docker/Dockerfile` construye imagen Python.
- `infra/docker/docker-compose.prod.yml` orquesta app, Postgres, Redis y Nginx.
- `infra/docker/nginx/nginx.conf.template` define TLS, HTTP/2, headers y rate limits.

Riesgos:

- Scripts de deploy todavía hacen health checks directos a puerto 4000.
- En compose productivo, el puerto 4000 no se publica al host; Nginx es el punto de entrada.

### CI

Workflow activo:

- `.github/workflows/ci.yml`

Cubre:

- Ruff check.
- Ruff format check.
- Pytest con PostgreSQL.
- Typecheck declarado como omitido para legacy.
- Build/push de Docker image a GHCR en `main`.

Workflow histórico:

- `infra/ci/github-actions/ci.yml`

### Observabilidad

Archivos presentes:

- `observability/prometheus/prometheus.yml`
- `observability/loki/loki-config.yml`
- `observability/grafana/provisioning/README.md`

Brecha:

- Prometheus todavía apunta a `api-gateway:4000`, no a la topología Python/Nginx actual.

## Brechas Prioritarias

1. Elegir una sola ruta Alembic y mover `channel_mappings` a la migración canónica.
2. Agregar modelo SQLAlchemy o migración explícita para `channel_mappings`.
3. Conectar `POST /api/v1/tasks` con Celery o documentarlo como creación síncrona/pending.
4. Conectar `Odin._invoke_module()` con handlers reales.
5. Alinear ejecución dinámica de webhooks con clases `Handler`.
6. Implementar o remover consumo de `/api/v1/usage` en dashboard.
7. Agregar `WHATSAPP_APP_SECRET` a settings/env.
8. Hacer CORS configurable desde entorno.
9. Actualizar scripts de deploy para validar por Nginx.
10. Actualizar Prometheus al target real.

## Próximas Acciones Recomendadas

Orden sugerido:

1. Resolver migraciones y `channel_mappings`.
2. Corregir settings faltantes y CORS.
3. Conectar tareas async con Celery.
4. Unificar ejecución de módulos entre Odin, worker y webhooks.
5. Ajustar dashboard a endpoints reales o implementar `/api/v1/usage`.
6. Actualizar observabilidad y scripts de deploy.
7. Decidir si los scaffolds TS se mantienen como roadmap explícito o se reducen.
