const fs = require('fs');

const deployScript = `#!/bin/bash
set -e

cd /opt/ai-platform

echo "Pulling latest image from ghcr.io..."
docker compose -f infra/docker/docker-compose.prod.yml pull

echo "Starting services..."
docker compose -f infra/docker/docker-compose.prod.yml up -d

echo "Waiting for services to start..."
sleep 15

echo "Checking health..."
curl -f http://localhost:4000/api/v1/health || {
  echo "ERROR: Health check failed"
  docker compose -f infra/docker/docker-compose.prod.yml logs --tail=50 app
  exit 1
}

echo "Cleaning up unused images..."
docker image prune -f
`;

fs.writeFileSync('infra/docker/scripts/deploy-vps.sh', deployScript);
