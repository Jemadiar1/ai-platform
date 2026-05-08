#!/bin/bash
# ============================================================
# Script de despliegue en VPS via SSH
# ============================================================
# Uso:
#   1. Configurar variables de entorno
#   2. Copiar .env.example a .env y completar variables
#   3. Ejecutar: ./deploy.sh
#
# Variables de entorno:
#   VPS_HOST     - IP o dominio del VPS
#   VPS_USER     - Usuario SSH (ej: "root" o "deploy")
#   VPS_SSH_KEY  - Ruta al archivo de clave SSH privada
#   VPS_SSH_PASS - Password SSH (alternativa a VPS_SSH_KEY)
#   REPO_URL     - URL del repositorio (opcional)
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.prod.yml"

echo "============================================"
echo "  AI Platform - Despliegue en VPS"
echo "============================================"

# Validar variables de entorno
if [ -z "$VPS_HOST" ]; then
    echo "ERROR: VPS_HOST no está configurado."
    echo "Exporta la variable: export VPS_HOST='tu-vps-ip'"
    exit 1
fi

if [ -z "$VPS_USER" ]; then
    echo "ERROR: VPS_USER no está configurado."
    echo "Exporta la variable: export VPS_USER='deploy'"
    exit 1
fi

# Validar autenticación SSH
if [ -z "$VPS_SSH_KEY" ] && [ -z "$VPS_SSH_PASS" ]; then
    echo "ERROR: Necesitas configurar VPS_SSH_KEY o VPS_SSH_PASS."
    echo "Se recomienda usar clave SSH (VPS_SSH_KEY) por seguridad."
    exit 1
fi

# Determinar el comando SSH
SSH_CMD="ssh"
if [ -n "$VPS_SSH_KEY" ]; then
    if [ ! -f "$VPS_SSH_KEY" ]; then
        echo "ERROR: El archivo de clave SSH no existe: $VPS_SSH_KEY"
        exit 1
    fi
    SSH_CMD="ssh -i $VPS_SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
elif [ -n "$VPS_SSH_PASS" ]; then
    if ! command -v sshpass &> /dev/null; then
        echo "ERROR: sshpass no está instalado. Instálalo con:"
        echo "  Debian/Ubuntu: apt install sshpass"
        echo "  macOS: brew install sshpass"
        exit 1
    fi
    SSH_CMD="sshpass -p '$VPS_SSH_PASS' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
fi

# Determinar repositorio
REPO_URL="${REPO_URL:-https://github.com/Jemadiar1/ai-platform.git}"

# Verificar conectividad
echo "[1/6] Verificando conexión al VPS ($VPS_HOST)..."
if $SSH_CMD -p 22 "$VPS_USER@$VPS_HOST" "echo 'OK - Connected'" &> /dev/null; then
    echo "  OK - Conectado"
else
    echo "  Warning: No se pudo conectar. Verifica credenciales."
    echo "  VPS_HOST=$VPS_HOST"
    echo "  VPS_USER=$VPS_USER"
    exit 1
fi

# Clonar/clonar repositorio
echo "[2/6] Preparando repositorio en /opt/ai-platform..."
$SSH_CMD -p 22 "$VPS_USER@$VPS_HOST" "
    cd /opt &&
    if [ -d ai-platform ]; then
        echo 'Repositorio existente, ejecutando git pull...'
        cd ai-platform && git pull
    else
        echo 'Clonando repositorio...'
        git clone $REPO_URL
    fi
"

# Verificar Docker
echo "[3/6] Verificando Docker..."
DOCKER_VERSION=$($SSH_CMD -p 22 "$VPS_USER@$VPS_HOST" "docker --version" 2>&1)
if [ $? -eq 0 ]; then
    echo "  OK - $DOCKER_VERSION"
else
    echo "  ERROR - Docker no está instalado en el VPS"
    echo "  Instalar: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

# Verificar .env
echo "[4/6] Verificando configuración..."
$SSH_CMD -p 22 "$VPS_USER@$VPS_HOST" "
    cd /opt/ai-platform/infra/docker &&
    if [ ! -f .env ]; then
        echo 'ERROR: .env no existe. Copiar .env.example a .env y completar variables.'
        exit 1
    fi
    echo '  OK - .env encontrado'
"

# Construir y levantar
echo "[5/6] Construyendo imagen Docker..."
$SSH_CMD -p 22 "$VPS_USER@$VPS_HOST" "
    cd /opt/ai-platform/infra/docker &&
    docker compose -f docker-compose.prod.yml build --no-cache
"

echo "[6/6] Levantando servicios..."
$SSH_CMD -p 22 "$VPS_USER@$VPS_HOST" "
    cd /opt/ai-platform/infra/docker &&
    docker compose -f docker-compose.prod.yml up -d
"

# Verificar servicios
echo ""
echo "Esperando a que los servicios arrancan..."
sleep 15

echo "Verificando health check..."
HEALTH_RESPONSE=$($SSH_CMD -p 22 "$VPS_USER@$VPS_HOST" "curl -s http://localhost:4000/api/v1/health" 2>&1)

if [ $? -eq 0 ] && echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
    echo ""
    echo "============================================"
    echo "  AI Platform desplegado exitosamente"
    echo "============================================"
    echo ""
    echo "  API:        http://$VPS_HOST:4000"
    echo "  Swagger:    http://$VPS_HOST:4000/docs"
    echo "  Health:     http://$VPS_HOST:4000/api/v1/health"
    echo ""
    echo "  Comandos útiles:"
    echo "    ssh $VPS_USER@$VPS_HOST"
    echo "    cd /opt/ai-platform/infra/docker"
    echo "    docker compose -f docker-compose.prod.yml logs -f app"
    echo "    docker compose -f docker-compose.prod.yml down"
    echo "    docker compose -f docker-compose.prod.yml restart"
    echo ""
else
    echo ""
    echo "============================================"
    echo "  Servicios levantados pero health check falló"
    echo "============================================"
    echo ""
    echo "  Ver logs: ssh $VPS_USER@$VPS_HOST 'cd /opt/ai-platform/infra/docker && docker compose -f docker-compose.prod.yml logs app'"
    echo ""
    $SSH_CMD -p 22 "$VPS_USER@$VPS_HOST" "cd /opt/ai-platform/infra/docker && docker compose -f docker-compose.prod.yml ps"
fi
