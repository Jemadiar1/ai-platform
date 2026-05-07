# AI Platform Architecture

Documento base de arquitectura para AI Platform.

## Capas

1. Frontend: `apps/dashboard`, `apps/admin`, `apps/website`
2. API Gateway: `services/api-gateway`
3. Orchestrator: `services/orchestrator`
4. Modulos de negocio: `modules/ai-*`
5. Tools / Skills: `packages/*`, `modules/*/tools` y `services/orchestrator/config/skills`
6. Workers async: `workers/task-runner`, `workers/scheduler`
7. Data: PostgreSQL, Redis, pgvector o Qdrant
8. Observability: `observability/*`

## Enfoque de fase 1

La base actual sigue una estrategia `modular monolith + orchestrator + workers`.

- `services/api-gateway` expone la API publica y resuelve contexto de tenant.
- `services/orchestrator` coordina tareas, decide rutas y conversa con los modulos.
- `modules/ai-*` encapsulan reglas de negocio por dominio, sin obligar un despliegue separado desde el inicio.
- `workers/*` procesan trabajos largos y reintentos.

Cada modulo debe organizarse con estas carpetas:

- `application/`: casos de uso
- `domain/`: entidades y reglas
- `infrastructure/`: adaptadores y clientes externos
- `contracts/`: DTOs y schemas
- `prompts/`: prompts versionados
- `tools/`: funciones atomicas del modulo
- `tests/`: pruebas del dominio y casos de uso

## Multi-tenancy

- Cada entidad debe incluir `tenant_id`
- Todas las APIs deben operar bajo `/api/v1`
- El aislamiento de datos es obligatorio desde el primer commit
