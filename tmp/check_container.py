import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('147.93.3.250', 22, 'root', '?4RNspjf6hii1zWx', timeout=15)

# Verificar si el archivo en el container tiene el await
_, o, _ = s.exec_command(
    'docker exec ai-platform-api grep -n "validate_webhook" /app/src/ai_platform/api/v1/webhooks.py'
)
print(o.read().decode('utf-8', 'replace'))

s.close()
