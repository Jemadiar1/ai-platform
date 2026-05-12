# ADR-002: Multi-tenancy first

## Estado

Aceptado

## Decision

Toda tabla y flujo distribuido propaga `tenant_id` desde el API Gateway hasta modulos, workers y almacenamiento.
