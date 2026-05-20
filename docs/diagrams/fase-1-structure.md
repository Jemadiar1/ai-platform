# Diagrama De Estructura Fase 1

Estado del documento: 2026-05-20

## Vista De Runtime Actual

```mermaid
flowchart TD
    subgraph External[Entradas externas]
        USER[Usuarios web]
        CLERK[Clerk webhook]
        STRIPE[Stripe webhook]
        TG[Telegram]
        WA[WhatsApp]
        DC[Discord]
    end

    subgraph Edge[Edge productivo]
        NGINX[Nginx<br/>TLS, rate limits, headers]
    end

    subgraph Backend[Backend Python]
        FASTAPI[FastAPI app<br/>backend/src/ai_platform/main.py]
        API[API v1 routers]
        RAGNAR[Ragnar orchestrator]
        CHANNELS[Channel adapters]
        MODULES[Python modules ai-*]
        CELERY[Celery task runner]
    end

    subgraph Data[Data]
        PG[(PostgreSQL)]
        REDIS[(Redis)]
    end

    USER --> NGINX
    CLERK --> NGINX
    STRIPE --> NGINX
    TG --> NGINX
    WA --> NGINX
    DC --> NGINX
    NGINX --> FASTAPI
    FASTAPI --> API
    API --> RAGNAR
    API --> CHANNELS
    RAGNAR --> MODULES
    API --> PG
    API --> REDIS
    CELERY --> MODULES
    CELERY --> PG
    CELERY --> REDIS
```

## Vista De Monorepo

```text
AI-Platform/
├── apps/
│   ├── admin/                 # Next.js placeholder
│   ├── dashboard/             # Next.js prototype; consume API local
│   └── website/               # Next.js placeholder
├── backend/
│   ├── src/ai_platform/
│   │   ├── api/v1/            # FastAPI routers
│   │   ├── channels/          # Telegram, WhatsApp, Discord
│   │   ├── core/              # Settings y seguridad
│   │   ├── models/            # SQLAlchemy y channel mappings SQL
│   │   ├── modules/           # Handlers Python ai_*
│   │   ├── orchestrator/      # Ragnar y subsistemas
│   │   ├── services/          # Billing y servicios internos
│   │   └── workers/           # Celery task runner
│   ├── tests/                 # Pytest backend
│   ├── alembic/               # Árbol Alembic usado por migrate.py
│   └── migrations/alembic/    # Árbol Alembic copiado por Dockerfile
├── docs/
│   ├── adr/
│   ├── diagrams/
│   ├── reports/
│   └── runbooks/
├── infra/
│   ├── compose/               # Docker Compose local Postgres/Redis
│   ├── docker/                # Dockerfile, compose prod, Nginx
│   └── ci/                    # CI histórico TS
├── modules/
│   └── ai-*/                  # Scaffolds de dominio
├── observability/
│   ├── prometheus/
│   ├── loki/
│   └── grafana/
├── packages/
│   ├── sdk/
│   ├── shared-prompts/
│   ├── shared-schemas/
│   ├── shared-types/
│   └── ui-kit/
├── services/
│   ├── api-gateway/           # Fastify mínimo
│   └── orchestrator/          # Configuración, sin runtime TS principal
└── workers/
    ├── scheduler/             # Worker TS mínimo
    └── task-runner/           # Worker TS mínimo
```

## Flujo De Una Tarea API

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI /api/v1/tasks
    participant DB as PostgreSQL
    participant Queue as Redis/Celery
    participant Worker as Celery worker
    participant Module as ai_platform.modules.ai_*

    Client->>API: POST /api/v1/tasks
    API->>DB: crea Task(status=pending)
    Note over API,Queue: Publicación a Celery todavía pendiente
    Worker->>DB: lee/actualiza Task cuando recibe job
    Worker->>Module: importa Handler y ejecuta action
    Worker->>DB: guarda resultado, status y usage
```

## Flujo De Canales

```mermaid
sequenceDiagram
    participant Channel as Telegram/WhatsApp/Discord
    participant API as FastAPI webhook
    participant Map as channel_mappings
    participant Ragnar
    participant Module as Module execution
    participant Adapter as Channel adapter

    Channel->>API: POST /api/v1/webhooks/{channel}
    API->>Map: busca o crea mapping
    API->>Ragnar: decide módulo y acción
    API->>Module: ejecuta handler dinámico
    API->>Adapter: envía respuesta
    Adapter->>Channel: mensaje final
```

Riesgo: el flujo depende de `channel_mappings`, pero esa tabla no está alineada entre modelos y migraciones canónicas.

## Estado Por Bloque

| Bloque | Estado actual |
| --- | --- |
| Backend FastAPI | Implementado y es el runtime principal. |
| Ragnar | Implementado para decisión, contexto y fallback; ejecución directa de módulo sigue placeholder. |
| Worker Celery | Implementado parcialmente; no está conectado desde `POST /tasks`. |
| Módulos Python | `ai-connect` tiene más lógica; el resto son stubs. |
| Apps Next.js | Dashboard prototipo; admin y website placeholders. |
| Services TS | Scaffolds mínimos, no son el runtime productivo. |
| Infra Docker prod | App Python + Postgres + Redis + Nginx. |
| Observabilidad | Configuración base, con target Prometheus desactualizado. |
