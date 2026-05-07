# Diagrama de Estructura Fase 1

## Vista de alto nivel

```mermaid
flowchart TD
    U[Usuarios / Clientes / Admin] --> FE[Apps Next.js]
    FE --> GW[API Gateway]
    GW --> ORCH[Orchestrator]
    ORCH --> MOD[Modulos de negocio ai-*]
    ORCH --> WK[Workers]
    MOD --> PKG[Packages compartidos]
    GW --> DATA[(PostgreSQL / Redis / Qdrant)]
    ORCH --> DATA
    WK --> DATA
    FE --> OBS[Observability]
    GW --> OBS
    ORCH --> OBS
    WK --> OBS
```

## Estructura completa del repositorio

```text
ai-platform/
├── .env.example
├── .gitignore
├── package.json
├── pnpm-workspace.yaml
├── README.md
├── tsconfig.base.json
├── turbo.json
│
├── apps/
│   ├── admin/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── next.config.mjs
│   │   ├── package.json
│   │   └── tsconfig.json
│   ├── dashboard/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── next.config.mjs
│   │   ├── package.json
│   │   └── tsconfig.json
│   └── website/
│       ├── app/
│       │   ├── layout.tsx
│       │   └── page.tsx
│       ├── next.config.mjs
│       ├── package.json
│       └── tsconfig.json
│
├── docs/
│   ├── architecture.md
│   ├── adr/
│   │   ├── ADR-001-monorepo.md
│   │   └── ADR-002-multi-tenancy.md
│   ├── diagrams/
│   │   └── fase-1-structure.md
│   ├── reports/
│   │   └── 2026-04-16-architecture-refactor-report.md
│   └── runbooks/
│       └── development.md
│
├── infra/
│   ├── ci/
│   │   └── github-actions/
│   │       └── ci.yml
│   ├── compose/
│   │   └── docker-compose.dev.yml
│   ├── docker/
│   │   └── README.md
│   └── k8s/
│       └── base/
│           └── namespace.yaml
│
├── modules/
│   ├── ai-ads/
│   │   ├── README.md
│   │   ├── application/
│   │   │   └── handler.py
│   │   ├── contracts/
│   │   │   └── README.md
│   │   ├── domain/
│   │   │   └── README.md
│   │   ├── infrastructure/
│   │   │   └── README.md
│   │   ├── prompts/
│   │   │   └── system.txt
│   │   ├── tests/
│   │   │   └── test_module.py
│   │   └── tools/
│   │       └── README.md
│   ├── ai-analytics/
│   │   ├── README.md
│   │   ├── application/
│   │   │   └── handler.py
│   │   ├── contracts/
│   │   │   └── README.md
│   │   ├── domain/
│   │   │   └── README.md
│   │   ├── infrastructure/
│   │   │   └── README.md
│   │   ├── prompts/
│   │   │   └── system.txt
│   │   ├── tests/
│   │   │   └── test_module.py
│   │   └── tools/
│   │       └── README.md
│   ├── ai-connect/
│   │   ├── README.md
│   │   ├── application/
│   │   │   └── handler.py
│   │   ├── contracts/
│   │   │   └── README.md
│   │   ├── domain/
│   │   │   └── README.md
│   │   ├── infrastructure/
│   │   │   └── README.md
│   │   ├── prompts/
│   │   │   └── system.txt
│   │   ├── tests/
│   │   │   └── test_module.py
│   │   └── tools/
│   │       └── README.md
│   ├── ai-content/
│   │   ├── README.md
│   │   ├── application/
│   │   │   └── handler.py
│   │   ├── contracts/
│   │   │   └── README.md
│   │   ├── domain/
│   │   │   └── README.md
│   │   ├── infrastructure/
│   │   │   └── README.md
│   │   ├── prompts/
│   │   │   └── system.txt
│   │   ├── tests/
│   │   │   └── test_module.py
│   │   └── tools/
│   │       └── README.md
│   ├── ai-leads/
│   │   ├── README.md
│   │   ├── application/
│   │   │   └── handler.py
│   │   ├── contracts/
│   │   │   └── README.md
│   │   ├── domain/
│   │   │   └── README.md
│   │   ├── infrastructure/
│   │   │   └── README.md
│   │   ├── prompts/
│   │   │   └── system.txt
│   │   ├── tests/
│   │   │   └── test_module.py
│   │   └── tools/
│   │       └── README.md
│   ├── ai-social/
│   │   ├── README.md
│   │   ├── application/
│   │   │   └── handler.py
│   │   ├── contracts/
│   │   │   └── README.md
│   │   ├── domain/
│   │   │   └── README.md
│   │   ├── infrastructure/
│   │   │   └── README.md
│   │   ├── prompts/
│   │   │   └── system.txt
│   │   ├── tests/
│   │   │   └── test_module.py
│   │   └── tools/
│   │       └── README.md
│   └── ai-web/
│       ├── README.md
│       ├── application/
│       │   └── handler.py
│       ├── contracts/
│       │   └── README.md
│       ├── domain/
│       │   └── README.md
│       ├── infrastructure/
│       │   └── README.md
│       ├── prompts/
│       │   └── system.txt
│       ├── tests/
│       │   └── test_module.py
│       └── tools/
│           └── README.md
│
├── observability/
│   ├── grafana/
│   │   └── provisioning/
│   │       └── README.md
│   ├── loki/
│   │   └── loki-config.yml
│   └── prometheus/
│       └── prometheus.yml
│
├── packages/
│   ├── sdk/
│   │   ├── package.json
│   │   └── src/
│   │       ├── js/
│   │       │   └── index.ts
│   │       └── python/
│   │           └── __init__.py
│   ├── shared-prompts/
│   │   ├── package.json
│   │   └── src/
│   │       └── index.ts
│   ├── shared-schemas/
│   │   ├── package.json
│   │   └── src/
│   │       └── index.ts
│   ├── shared-types/
│   │   ├── package.json
│   │   └── src/
│   │       └── index.ts
│   └── ui-kit/
│       ├── package.json
│       └── src/
│           └── index.tsx
│
├── services/
│   ├── api-gateway/
│   │   ├── package.json
│   │   ├── src/
│   │   │   └── index.ts
│   │   └── tsconfig.json
│   └── orchestrator/
│       ├── .env.example
│       ├── Dockerfile
│       └── config/
│           ├── clients/
│           │   └── README.md
│           ├── skills/
│           │   └── README.md
│           └── SOUL.md
│
└── workers/
    ├── scheduler/
    │   ├── package.json
    │   ├── src/
    │   │   └── index.ts
    │   └── tsconfig.json
    └── task-runner/
        ├── package.json
        ├── src/
        │   └── index.ts
        └── tsconfig.json
```

## Diagrama de responsabilidades

```mermaid
flowchart LR
    subgraph Apps
        A1[dashboard]
        A2[admin]
        A3[website]
    end

    subgraph Services
        S1[api-gateway]
        S2[orchestrator]
    end

    subgraph Modules
        M1[ai-connect]
        M2[ai-web]
        M3[ai-content]
        M4[ai-social]
        M5[ai-leads]
        M6[ai-ads]
        M7[ai-analytics]
    end

    subgraph Workers
        W1[task-runner]
        W2[scheduler]
    end

    subgraph Shared
        P1[shared-types]
        P2[shared-schemas]
        P3[shared-prompts]
        P4[ui-kit]
        P5[sdk]
    end

    A1 --> S1
    A2 --> S1
    A3 --> S1
    S1 --> S2
    S2 --> M1
    S2 --> M2
    S2 --> M3
    S2 --> M4
    S2 --> M5
    S2 --> M6
    S2 --> M7
    S2 --> W1
    S2 --> W2
    M1 --> P1
    M2 --> P1
    M3 --> P2
    M4 --> P3
    M5 --> P5
    M6 --> P2
    M7 --> P1
    A1 --> P4
    A2 --> P4
    A3 --> P4
```

