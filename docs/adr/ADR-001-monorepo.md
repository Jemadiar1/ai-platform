# ADR-001: Monorepo Con Turborepo

## Estado

Aceptado. Revisado el 2026-05-20.

## Contexto

El proyecto necesita compartir tipos, schemas, prompts, utilidades de UI y convenciones entre apps, servicios, workers y módulos de negocio. En fase temprana también necesita reducir fricción operativa y evitar repositorios separados antes de que existan límites estables.

Desde la decisión original, el repositorio incorporó un backend Python completo en `backend/`, separado del workspace pnpm. Ese backend es hoy el runtime principal.

## Decisión

Usar un monorepo con pnpm workspaces y Turborepo para el código TypeScript/JavaScript:

- `apps/*`
- `services/*`
- `workers/*`
- `packages/*`

Mantener el backend Python dentro del mismo repositorio, pero gestionado con Poetry:

- `backend/pyproject.toml`
- `backend/src/ai_platform`
- `backend/tests`

## Estado Actual

Workspace pnpm:

- `apps/dashboard`, `apps/admin`, `apps/website`
- `services/api-gateway`, `services/orchestrator`
- `workers/scheduler`, `workers/task-runner`
- `packages/sdk`, `shared-types`, `shared-schemas`, `shared-prompts`, `ui-kit`

Backend Poetry:

- FastAPI
- SQLAlchemy
- Alembic
- Ragnar
- módulos Python `ai_*`
- worker Celery

## Consecuencias

- El monorepo sigue siendo la unidad de revisión, CI y despliegue.
- Turborepo no gobierna automáticamente el backend Python.
- Los comandos raíz `pnpm build`, `pnpm lint`, `pnpm test` cubren el workspace TS según configuración Turbo, no sustituyen los comandos Poetry del backend.
- La documentación y CI deben dejar claro qué validaciones aplican a cada stack.

## Reglas De Mantenimiento

- Las dependencias TypeScript se agregan en el workspace correspondiente y se coordinan con `pnpm-workspace.yaml`.
- Las dependencias Python se agregan en `backend/pyproject.toml`.
- Los paquetes compartidos TS no deben asumir que el backend Python los consume directamente.
- Si una pieza TS pasa de placeholder a runtime productivo, debe documentarse su puerto, contrato, despliegue y relación con el backend Python.
