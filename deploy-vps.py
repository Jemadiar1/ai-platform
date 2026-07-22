#!/usr/bin/env python3
"""
Desplegar AI Platform en VPS vía SSH con contraseña (paramiko).

Usar variables de entorno para credenciales:
    export VPS_HOST=100.86.8.81
    export VPS_USER=deploy
    export VPS_SSH_KEY=~/.ssh/id_rsa   # o VPS_SSH_PASS=password
    export REPO_URL=https://github.com/...

Ejecutar:
    python deploy-vps.py
"""

import os
import sys
import time

try:
    import paramiko
except ImportError:
    print("Instalando paramiko...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
    import paramiko

# Leer credenciales desde variables de entorno (nunca hardcodear)
VPS_HOST = os.environ.get("VPS_HOST")
if not VPS_HOST:
    print("ERROR: VPS_HOST es requerido. Configure la variable de entorno.")
    sys.exit(1)

VPS_PORT = 22
VPS_USER = os.environ.get("VPS_USER", "deploy")
if VPS_USER == "root":
    print("ADVERTENCIA: Usando root no es recomendado. Use un usuario con sudo.")

VPS_SSH_KEY = os.environ.get("VPS_SSH_KEY")
VPS_SSH_PASS = os.environ.get("VPS_SSH_PASS")
REPO_URL = os.environ.get("REPO_URL", "https://github.com/Jemadiar1/ai-platform.git")
REMOTE_PATH = "/opt/ai-platform"

if not VPS_SSH_KEY and not VPS_SSH_PASS:
    print("ERROR: Debes configurar VPS_SSH_KEY o VPS_SSH_PASS como variable de entorno.")
    print("Ejemplo:")
    print("  set VPS_SSH_KEY=C:\\Users\\TuUsuario\\.ssh\\id_rsa")
    print("  o set VPS_SSH_PASS=tu_password")
    sys.exit(1)


def run_remote(ssh, cmd, timeout=120):
    """Ejecutar comando en servidor remoto."""
    print(f"  $ {cmd}")
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        if output:
            for line in output.split("\n"):
                print(f"    {line}")
        if error:
            for line in error.split("\n"):
                if line:
                    print(f"    ERR: {line}")
        return output, error
    except Exception as e:
        print(f"    ERROR: {e}")
        return "", str(e)


def main():
    print("=" * 60)
    print("  AI Platform - Deploy to VPS")
    print("=" * 60)
    print()

    # Paso 1: Conectar
    print("[1/6] Conectando al VPS...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connected = False
    try:
        if VPS_SSH_KEY:
            print(f"  Intentando key SSH: {VPS_SSH_KEY}...")
            ssh.connect(
                VPS_HOST,
                port=VPS_PORT,
                username=VPS_USER,
                key_filename=VPS_SSH_KEY,
                timeout=15,
                allow_agent=False,
                look_for_keys=False,
            )
            print("  ¡Conectado con key SSH!")
            connected = True
    except (paramiko.AuthenticationException, paramiko.SSHException):
        print("  Key SSH no funciona, intentando password...")
    except Exception as e:
        print(f"  Error con key: {e}")

    if not connected:
        if not VPS_SSH_PASS:
            print("  ERROR: Ninguna autenticación disponible (key ni password).")
            return 1
        print(f"  Usando password para {VPS_USER}@{VPS_HOST}...")
        try:
            ssh.connect(
                VPS_HOST,
                port=VPS_PORT,
                username=VPS_USER,
                password=VPS_SSH_PASS,
                timeout=15,
            )
            print("  ¡Conectado con password!")
            connected = True
        except Exception as e:
            print(f"  ERROR: {e}")
            return 1

    if not connected:
        print("  ERROR: No se pudo conectar.")
        return 1

    try:
        # Paso 2: Clonar repositorio
        print("[2/6] Clonando repositorio...")
        run_remote(ssh, f"cd /opt && [ -d ai-platform ] || git clone {REPO_URL}")

        # Paso 3: Crear .env
        print("[3/6] Configurando .env...")
        run_remote(ssh, f"[ -f {REMOTE_PATH}/infra/docker/.env ] || cp {REMOTE_PATH}/infra/docker/.env.example {REMOTE_PATH}/infra/docker/.env")
        print("  .env created (edit it on the VPS)")

        # Paso 4: Verificar Docker
        print("[4/6] Verificando Docker...")
        run_remote(ssh, "docker --version")
        run_remote(ssh, "docker compose version")

        # Paso 5: Construir y desplegar
        print("[5/6] Construyendo y desplegando...")
        run_remote(ssh, f"cd {REMOTE_PATH}/infra/docker && docker compose -f docker-compose.prod.yml build --no-cache")
        run_remote(ssh, f"cd {REMOTE_PATH}/infra/docker && docker compose -f docker-compose.prod.yml up -d")

        # Paso 6: Verificar
        print("[6/6] Verificando...")
        time.sleep(5)
        run_remote(ssh, f"docker compose -f {REMOTE_PATH}/infra/docker/docker-compose.prod.yml ps")
        run_remote(ssh, "docker exec ai-platform-api curl -s http://localhost:4000/api/v1/health")

    finally:
        ssh.close()

    print()
    print("=" * 60)
    print("  Deployment Complete!")
    print("=" * 60)
    print()
    print(f"  API:  http://{VPS_HOST}:4000")
    print(f"  Docs: http://{VPS_HOST}:4000/docs")
    print()
    print("  On VPS:")
    print(f"    cd {REMOTE_PATH}/infra/docker")
    print("    docker compose -f docker-compose.prod.yml logs -f app")
    print("    docker compose -f docker-compose.prod.yml down")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
