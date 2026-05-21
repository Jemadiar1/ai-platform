import paramiko, time

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('147.93.3.250', 22, 'root', '?4RNspjf6hii1zWx', timeout=15)

# Detener y eliminar container
s.exec_command('docker stop ai-platform-api && docker rm ai-platform-api')
time.sleep(3)

# Eliminar imagen vieja
s.exec_command('docker rmi ghcr.io/jemadiar1/ai-platform:latest 2>/dev/null; echo done')
time.sleep(2)

# Pull la imagen nueva del commit con el fix
s.exec_command('docker pull ghcr.io/jemadiar1/ai-platform:latest')
time.sleep(15)

# Verificar que la imagen tiene el fix
_, o, _ = s.exec_command(
    'docker run --rm ghcr.io/jemadiar1/ai-platform:latest grep -n "validation = " /app/src/ai_platform/api/v1/webhooks.py 2>/dev/null || echo IMAGE_CHECK_DONE'
)
print('IMAGE CHECK:')
print(o.read().decode('utf-8', 'replace'))

# Crear y arrancar
s.exec_command(
    'cd /opt/ai-platform && docker compose -f infra/docker/docker-compose.prod.yml up -d app'
)
time.sleep(20)

# Health check
_, o, _ = s.exec_command('curl -sk https://localhost/api/v1/health')
print('\nHEALTH:', o.read().decode().strip())

# Verificar fix en container nuevo
_, o, _ = s.exec_command(
    'docker exec ai-platform-api grep -n "validation = " /app/src/ai_platform/api/v1/webhooks.py | head -5'
)
print('\nCONTAINER CHECK:')
print(o.read().decode('utf-8', 'replace'))

s.close()
