#!/bin/bash
# ============================================================
# Script de despliegue en VPS
# ============================================================
# Uso:
#   1. Copiar .env.example a .env y completar variables
#   2. Ejecutar: ./deploy.sh
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.prod.yml"

echo "============================================"
echo "  AI Platform - Despliegue en VPS"
echo "============================================"

# Verificar Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker no está instalado"
    echo "Instalar: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

echo "[1/6] Verificando Docker..."
docker info &> /dev/null && echo "  OK - Docker funcionando"

# Verificar .env
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "[2/6] Copiando .env.example a .env..."
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo "  ⚠️  Editar .env con tus claves antes de continuar"
    echo "  Ejecutar: nano .env"
    exit 1
fi
echo "[2/6] .env encontrado"

# Verificar variables críticas
echo "[3/6] Verificando variables de entorno..."
REQUIRED_VARS=(
    "SECRET_KEY"
    "CLERK_SECRET_KEY"
    "OPENROUTER_API_KEY"
    "POSTGRES_PASSWORD"
)

for var in "${REQUIRED_VARS[@]}"; do
    if ! grep -q "^${var}=" "$SCRIPT_DIR/.env" 2>/dev/null; then
        echo "  ⚠️  Variable $var no configurada en .env"
    fi
done

# Construir y levantar
echo "[4/6] Construyendo imagen Docker..."
docker compose -f "$COMPOSE_FILE" build --no-cache

echo "[5/6] Levantando servicios..."
docker compose -f "$COMPOSE_FILE" up -d

echo "[6/6] Verificando servicios..."
sleep 10

# Verificar health
if docker compose -f "$COMPOSE_FILE" ps | grep -q "healthy"; then
    echo ""
    echo "============================================"
    echo "  ✅ AI Platform desplegado exitosamente"
    echo "============================================"
    echo ""
    echo "  API:        http://tu-vps-ip:4000"
    echo "  Swagger:    http://tu-vps-ip:4000/docs"
    echo "  Health:     http://tu-vps-ip:4000/api/v1/health"
    echo ""
    echo "  Comandos útiles:"
    echo "    docker compose -f infra/docker/docker-compose.prod.yml logs -f app"
    echo "    docker compose -f infra/docker/docker-compose.prod.yml down"
    echo "    docker compose -f infra/docker/docker-compose.prod.yml restart"
    echo ""
else
    echo ""
    echo "============================================"
    echo "  ⚠️  Servicios levantados pero health check falló"
    echo "============================================"
    echo ""
    echo "  Ver logs: docker compose -f infra/docker/docker-compose.prod.yml logs app"
    echo ""
    docker compose -f "$COMPOSE_FILE" ps
fi
