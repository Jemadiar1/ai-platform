# ADR-002: Multi-Tenancy First

## Estado

Aceptado. Revisado el 2026-05-20.

## Contexto

AI Platform debe operar para múltiples tenants. El aislamiento de datos y la propagación de contexto de tenant son decisiones de base, no mejoras posteriores.

El backend actual centraliza la persistencia en PostgreSQL con SQLAlchemy y expone APIs bajo `/api/v1`. También recibe webhooks de canales externos, donde el tenant debe resolverse a partir de identidad de canal, usuario o configuración del proveedor.

## Decisión

Toda entidad persistente de negocio debe tener `tenant_id` cuando el dato pertenezca a un tenant. Los flujos API, worker, módulo y canal deben conservar ese contexto hasta almacenamiento, billing y observabilidad.

## Implementación Actual

Modelos SQLAlchemy con `tenant_id`:

- `User`
- `Task`
- `UsageEvent`
- `AgentMemory`
- `Session`
- `Message`

Modelo raíz:

- `Tenant`

Flujos que ya propagan o usan tenant:

- `POST /api/v1/tasks` recibe `tenant_id`.
- `GET /api/v1/tasks` filtra por `tenant_id`.
- `GET /api/v1/tenants/me` consulta el tenant actual desde dependencia de auth.
- Webhooks de canales resuelven o intentan resolver tenant mediante mapping.
- Ragnar recibe `tenant_id` en decisiones y ejecución.
- Memoria, sesiones y eventos de uso están diseñados con alcance de tenant.

## Brechas Actuales

- `channel_mappings` está usado por webhooks y `models/channel_mapping.py`, pero no existe como modelo SQLAlchemy principal.
- Hay dos rutas de migraciones Alembic, y no ambas contienen `channel_mappings`.
- El worker Celery tiene TODO para obtener el `tenant_id` real al registrar usage.
- Algunas rutas dependen de contexto de auth simplificado o placeholder.
- La política de aislamiento todavía no está reforzada por Row Level Security en PostgreSQL.

## Reglas De Implementación

- Ninguna query de datos de negocio debe omitir filtro de `tenant_id` salvo que lea configuración global explícita.
- Los webhooks que no reciben `tenant_id` directo deben resolverlo por mapping persistente y auditable.
- Los módulos `ai-*` no deben inferir tenant desde variables globales.
- Eventos de uso y billing deben registrar siempre tenant, módulo, acción, tokens y costo cuando estén disponibles.
- Las migraciones deben ser la fuente de verdad de estructura de datos. `create_tables.py` solo debe usarse como ayuda local.

## Implicaciones Operativas

Antes de usar canales en producción, hay que alinear:

1. Modelo de `channel_mappings`.
2. Migración canónica.
3. Tests de resolución tenant por canal.
4. Flujo de actualización de `last_session_id`.

Antes de habilitar billing real, hay que asegurar:

1. Registro consistente de `UsageEvent`.
2. Asociación Stripe customer/subscription con tenant.
3. Límites por plan y fallback cuando se exceden.
