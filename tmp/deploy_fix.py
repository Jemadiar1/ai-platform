import paramiko, time

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('147.93.3.250', 22, 'root', '?4RNspjf6hii1zWx', timeout=15)

# Pull del repo en la VPS
_, o, _ = s.exec_command('cd /opt/ai-platform && git pull origin main 2>&1')
print('GIT PULL:')
print(o.read().decode('utf-8', 'replace'))

# Verificar que ahora tiene el fix
_, o, _ = s.exec_command('grep -n "validate_webhook" /opt/ai-platform/backend/src/ai_platform/api/v1/webhooks.py')
print('\nLOCAL FILE AFTER PULL:')
print(o.read().decode('utf-8', 'replace'))

# Reconstruir
_, o, _ = s.exec_command(
    'cd /opt/ai-platform && docker compose -f infra/docker/docker-compose.prod.yml build --no-cache app 2>&1'
)
out = o.read().decode('utf-8', 'replace')
print('\nBUILD:')
print(out[-300:])

time.sleep(10)

# Recrear container
_, o, _ = s.exec_command(
    'cd /opt/ai-platform && docker compose -f infra/docker/docker-compose.prod.yml up -d app 2>&1'
)
print('\nUP:')
print(o.read().decode('utf-8', 'replace'))

time.sleep(15)

# Health check
_, o, _ = s.exec_command('curl -sk https://localhost/api/v1/health')
print('\nHEALTH:', o.read().decode().strip())

# Verificar fix en container
_, o, _ = s.exec_command(
    'docker exec ai-platform-api grep -n "validation = " /app/src/ai_platform/api/v1/webhooks.py | head -5'
)
print('\nCONTAINER CHECK:')
print(o.read().decode('utf-8', 'replace'))

s.close()
