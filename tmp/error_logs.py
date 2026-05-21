import paramiko

s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect('147.93.3.250', 22, 'root', '?4RNspjf6hii1zWx', timeout=15)

# Logs detallados
_, o, _ = s.exec_command('docker logs ai-platform-api --tail 100 2>&1')
out = o.read().decode('utf-8', 'replace')
print(out[-6000:])

s.close()
