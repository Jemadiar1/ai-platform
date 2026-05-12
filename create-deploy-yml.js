const fs = require('fs');

const deployYml = `name: Deploy to VPS

on:
  push:
    tags:
      - "v*.*.*"
  workflow_dispatch: {}

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: \${{ github.repository }}

jobs:
  build-and-push:
    name: Build and Push Docker Image
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Log in to Container Registry
        uses: docker/login-action@v3
        with:
          registry: \${{ env.REGISTRY }}
          username: \${{ github.actor }}
          password: \${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: \${{ env.REGISTRY }}/\${{ env.IMAGE_NAME }}
          tags: |
            type=sha,prefix=
            type=semver,pattern={{version}}
            type=raw,value=latest

      - name: Build and push Docker image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: ./infra/docker/Dockerfile
          push: true
          tags: \${{ steps.meta.outputs.tags }}
          labels: \${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy:
    name: Deploy to VPS
    runs-on: ubuntu-latest
    needs: [build-and-push]
    if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')
    environment: production
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Deploy to VPS via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: \${{ secrets.VPS_HOST }}
          username: \${{ secrets.VPS_USER }}
          key: \${{ secrets.DEPLOY_KEY }}
          port: 22
          script: |
            bash /opt/ai-platform/infra/docker/scripts/deploy-vps.sh

      - name: Health check retry
        run: |
          set -e
          for attempt in 1 2 3 4 5; do
            if curl -f http://\${{ secrets.VPS_HOST }}:4000/api/v1/health; then
              echo "Health check passed on attempt \$attempt"
              exit 0
            fi
            echo "Health check failed on attempt \$attempt, retrying in 10s..."
            sleep 10
          done
          echo "Health check failed after 5 attempts"
          exit 1

      - name: Notify success
        if: success()
        run: echo "Deployment successful for version \${{ github.ref_name }}"

      - name: Notify failure
        if: failure()
        run: echo "ERROR: Deployment failed for version \${{ github.ref_name }}"
`;

fs.writeFileSync('.github/workflows/deploy.yml', deployYml);
