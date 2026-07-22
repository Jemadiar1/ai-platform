# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AI Platform** is a multi-tenant AI marketing platform built by NeuralCrew Labs (under Digital Expressions). It automates marketing tasks (content, social, web, ads, analytics, leads, connect) using AI agents orchestrated by an internal system called **Odin**.

This is a **hybrid monorepo** with a Python backend as the production runtime and a TypeScript workspace as scaffold/future layer.

**Tech stack**: Python 3.11, FastAPI, SQLAlchemy 2.0, Pydantic v2, Celery + Redis, PostgreSQL 16 (pgvector), Clerk (auth), Stripe (billing), OpenRouter/NaN (LLM routing).

## Important Context Files

Read these first when working on architecture, development, infrastructure, modules, APIs, or deployment:

1. `AGENTS.md` — comprehensive behavioral instructions for agents working in this repo (business context, priorities, known gaps, deployment procedures)
2. `docs/architecture.md` — system architecture documentation
3. `docs/runbooks/development.md` — development runbook
4. `docs/reports/2026-05-20-current-state.md` — current project state report
5. `docs/adr/ADR-001-monorepo.md` and `ADR-002-multi-tenancy.md` — architectural decisions

**Key rule**: Documentation distinguishes between production-ready pieces and scaffolds. Not all monorepo content is ready for production.

## Monorepo Structure

```
AI-Platform/
├── backend/src/ai_platform/    # PRODUCTION RUNTIME: FastAPI Python backend
│   ├── main.py                 # Entry point (port 4000)
│   ├── api/v1/                 # API routes under /api/v1
│   ├── core/                   # config.py, security.py
│   ├── middleware/             # Logging, tenant, auth middleware
│   ├── models/                 # SQLAlchemy models
│   ├── schemas/                # Pydantic schemas
│   ├── services/               # Business logic services
│   ├── modules/                # ai-* Python modules (connect, social, content, etc.)
│   ├── orchestrator/           # Odin: LLM routing, plugins, subagents, skills
│   ├── channels/               # Telegram, WhatsApp, Discord adapters
│   ├── workers/                # Celery task runner
│   └── shared/                 # Shared types and constants
├── backend/alembic/            # Database migrations
├── backend/tests/              # pytest suite
├── apps/                       # TypeScript Next.js apps (scaffold state)
├── services/                   # TypeScript services (scaffold state)
├── workers/                    # TypeScript workers (scaffold state)
├── packages/                   # Shared TypeScript packages
├── modules/                    # Domain scaffolds (documentary, not runtime)
├── infra/                      # Docker, Compose, K8s, CI
├── observability/              # Prometheus, Grafana, Loki (scaffold)
├── docs/                       # Architecture docs, ADRs, runbooks
└── .github/workflows/ci.yml    # Active CI
```

## Runtime Topology

```
Internet --> Nginx (TLS, rate limits, ports 80/443) --> FastAPI (port 4000, internal)
                                                          |
                          +-------------------------------+-------------------------------+
                          |                               |                               |
                       PostgreSQL                    Redis                          Celery
                      (pgvector)                  (async/cache)                   (task queue)
                          |                               |                               |
                    Odin orchestrator              --> LLM providers
                          |
                       ai-* modules
```

## Commands

### Backend (Python)

Setup:
```powershell
cd backend
poetry install
```

Server:
```powershell
cd backend
poetry run task run
```

Celery worker:
```powershell
cd backend
poetry run celery -A ai_platform.workers.task_runner worker --loglevel=info
```

Tests:
```powershell
cd backend
poetry run pytest tests/ -v --tb=short --ignore-glob="**/test_modules/*"
```

Linting:
```powershell
cd backend
poetry run ruff check src
poetry run ruff format --check src
```

Type checking (mypy is configured but skipped in CI for legacy code):
```powershell
cd backend
poetry run mypy src
```

Migrations:
```powershell
cd backend
poetry run alembic upgrade head
```

Local dev (quick table setup, not a migration replacement):
```powershell
cd backend
poetry run python create_tables.py           # create tables
poetry run python create_tables.py --list     # list tables
poetry run python create_tables.py --drop     # drop all tables
```

### Environment Files

- **Root `.env.example`** — variables generales de desarrollo local
- **`infra/docker/.env.example`** — variables para despliegue productivo con Docker Compose y Nginx

The backend reads from `ai_platform.core.config.Settings` which pulls from `.env` or environment variables.

### TypeScript Workspace (pnpm + Turborepo)

Setup:
```powershell
pnpm install
```

Development:
```powershell
pnpm dev
```

Verification:
```powershell
pnpm build
pnpm lint
pnpm test
pnpm typecheck
```

Each app runs on its own port: website `:3000`, dashboard `:3001`, admin `:3002`.

### Docker / Infrastructure

Local dev:
```powershell
docker compose -f infra/compose/docker-compose.dev.yml up -d
docker compose -f infra/compose/docker-compose.dev.yml down
```

Production config validation:
```powershell
docker compose --env-file infra/docker/.env.example -f infra/docker/docker-compose.prod.yml config --quiet
```

Production topology: `infra/docker/docker-compose.prod.yml` orchestrates app, Postgres, Redis, and Nginx. Only Nginx exposes `80/443` publicly.

### CI/CD

GitHub Actions (`.github/workflows/ci.yml`):
- Triggers: push/PR to `main`
- Jobs: lint (Ruff check + format), typecheck (skipped/mypy), test (pytest with PostgreSQL 16 service), build-and-push (Docker to GHCR on main pushes)

## Key Architecture Principles

- **Multi-tenant first**: All business entities carry `tenant_id`, queries filter by tenant
- **API versioned** at `/api/v1`
- **Modular monolith**: Single FastAPI process with module-based separation, not yet microservices
- **Buy vs. build**: Auth (Clerk), billing (Stripe) are external
- **Configuration** must pass through `ai_platform.core.config.Settings`; avoid `os.environ` in app code
- **Migrations** (Alembic) are the source of truth for schema — `create_tables.py` is local help only

## Known Gaps

These are documented and should not be hidden by partial changes:

- `Odin._invoke_module()` returns a placeholder; direct Odin flow doesn't execute real handlers
- `POST /api/v1/tasks` creates tasks, but publishing to Celery is pending
- `apps/dashboard` consumes `/api/v1/usage` endpoint that doesn't exist
- CORS is hardcoded in FastAPI despite `CORS_ORIGINS` in Docker Compose
- Prometheus still points to `api-gateway:4000` instead of current Python+Nginx topology

**Resolved**: `channel_mappings` and `WHATSAPP_APP_SECRET` were aligned in migration 002 (`backend/alembic/versions/002_`).

Treat these as risk context, not automatic backlog. If a task touches a gap, fix only what's needed for the current objective.

## Development Rules

- Prefer the simplest solution that correctly meets the requirement
- Don't introduce abstractions, layers, or patterns without concrete observed need
- Don't fix adjacent problems just because you saw them — log as debt or suggestion
- Make surgical changes: touch only files necessary for the task
- Maintain existing style even if you'd prefer differently
- Verify before claiming something works — run the command, don't just say it passes
- All changes go through git commit and push; don't edit code directly on VPS as normal flow
