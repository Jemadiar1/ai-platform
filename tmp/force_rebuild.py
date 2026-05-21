import paramiko, time

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('147.93.3.250', 22, 'root', '?4RNspjf6hii1zWx', timeout=15)

# Verificar que el archivo LOCAL en el VPS tiene el fix
_, o, _ = s.exec_command('grep -n "validate_webhook" /opt/ai-platform/backend/src/ai_platform/api/v1/webhooks.py')
print('LOCAL FILE:')
print(o.read().decode('utf-8', 'replace'))

# Force rebuild con --no-cache
_, o, _ = s.exec_command(
    'cd /opt/ai-platform && docker compose -f infra/docker/docker-compose.prod.yml build --no-cache app 2>&1'
)
out = o.read().decode('utf-8', 'replace')
print('BUILD OUTPUT (last 500 chars):')
print(out[-500:])

s.close()
