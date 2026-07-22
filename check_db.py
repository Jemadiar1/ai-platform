#!/usr/bin/env python3
import subprocess

cmd = r"""sshpass -p 'Chucho1234' ssh -o StrictHostKeyChecking=no root@147.93.3.250 'docker exec ai-platform-postgres psql -U aiplatform -d ai_platform -c "select tablename from pg_tables where schemaname = '\''public'\'' order by tablename;"'"""
r = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8")
print(r.stdout)
print(r.stderr)