# AI Platform

Monorepo base para la plataforma multi-tenant de AI, construido a partir de la arquitectura objetivo definida para este proyecto.

## Estructura principal

- `apps/`: dashboard, admin y website en Next.js
- `services/`: API Gateway y orchestrator como procesos separados
- `modules/`: dominios de negocio `ai-*` listos para evolucionar a microservicios
- `workers/`: procesamiento asincrono y scheduler
- `packages/`: tipos, schemas, prompts, UI y SDK compartidos
- `infra/`: Docker, Compose, Kubernetes y CI
- `observability/`: Prometheus, Grafana y Loki
- `docs/`: arquitectura, ADRs y runbooks

## Principios aplicados

- Multi-tenancy first
- Arquitectura modular preparada para extraccion progresiva
- API versionada desde `/api/v1`
- Observabilidad desde el primer dia
- Buy vs. build para auth, billing y piezas no diferenciales
