# Documentación

Estado: 2026-05-20

## Lectura Recomendada

1. `architecture.md`: arquitectura vigente del repositorio.
2. `runbooks/development.md`: comandos de desarrollo, pruebas, Docker y advertencias operativas.
3. `reports/2026-05-20-current-state.md`: análisis detallado del estado actual.
4. `diagrams/fase-1-structure.md`: diagramas y estructura actual.
5. `adr/ADR-001-monorepo.md`: decisión sobre monorepo pnpm/Turborepo y backend Python.
6. `adr/ADR-002-multi-tenancy.md`: decisión y estado del multi-tenancy.

## Estado General

El backend productivo actual vive en `backend/src/ai_platform` y usa FastAPI, SQLAlchemy, Odin, módulos Python y worker Celery.

El workspace TypeScript mantiene apps, paquetes, servicios y workers, pero varias piezas siguen en estado scaffold o prototipo. La documentación vigente distingue explícitamente esas piezas para evitar asumir que todo el monorepo está listo para producción.

## Reportes Históricos

- `reports/2026-04-16-architecture-refactor-report.md`: explica la reorganización inicial hacia `modular monolith + orchestrator + workers`.
- `reports/2026-05-20-current-state.md`: refleja el estado real del código revisado el 2026-05-20.
