# Development Runbook

## Boot local

1. Copiar `.env.example` a `.env`
2. Levantar infraestructura base con `docker compose -f infra/compose/docker-compose.dev.yml up -d`
3. Instalar dependencias con `pnpm install`
4. Ejecutar `pnpm dev`

