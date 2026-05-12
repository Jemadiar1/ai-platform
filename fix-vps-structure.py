#!/usr/bin/env python3
"""
Corregir la estructura del repositorio Git en VPS.

Usar variables de entorno para credenciales:
    export VPS_HOST=100.86.8.81
    export VPS_USER=deploy
    export VPS_SSH_KEY=~/.ssh/id_rsa   # o VPS_SSH_PASS=password

Ejecutar:
    python fix-vps-structure.py

IMPORTANTE: Este script ejecuta rm -rf en el servidor remoto.
Asegúrese de tener un backup antes de ejecutarlo.
"""

import os
import sys
import getpass

try:
    import paramiko
except ImportError:
    print("Instalando paramiko...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
    import paramiko

# Leer credenciales desde variables de entorno
VPS_HOST = os.environ.get("VPS_HOST")
if not VPS_HOST:
    print("ERROR: VPS_HOST es requerido. Configure la variable de entorno.")
    sys.exit(1)

VPS_USER = os.environ.get("VPS_USER", "deploy")
if VPS_USER == "root":
    print("ADVERTENCIA: Usando root no es recomendado. Use un usuario con sudo.")

VPS_SSH_KEY = os.environ.get("VPS_SSH_KEY")
VPS_SSH_PASS = os.environ.get("VPS_SSH_PASS")

if not VPS_SSH_KEY and not VPS_SSH_PASS:
    print("ERROR: Debes configurar VPS_SSH_KEY o VPS_SSH_PASS como variable de entorno.")
    print("Ejemplo:")
    print("  set VPS_SSH_KEY=C:\\Users\\TuUsuario\\.ssh\\id_rsa")
    print("  o set VPS_SSH_PASS=tu_password")
    sys.exit(1)

REMOTE_PATH = "/opt/ai-platform"


def confirm_proceed() -> bool:
    """
    Confirmar antes de ejecutar operaciones destructivas en el servidor remoto.

    Retorna:
        True si el usuario confirma, False si cancela.
    """
    confirmation = getpass.getpass(
        "\nADVERTENCIA: Este script ejecutará rm -rf en el servidor remoto.\n"
        "Se eliminará el directorio Documents/AI-Platform/infra/docker si existe.\n"
        "¿Está seguro de continuar? [s/N] "
    )
    return confirmation.strip().lower() in ("s", "si", "y", "yes")


def main():
    print("=" * 60)
    print("  AI Platform - Fix VPS Structure")
    print("=" * 60)
    print()

    # Confirmar operación destructiva
    if not confirm_proceed():
        print("Operación cancelada por el usuario.")
        return 0

    # Conectar al VPS
    print(f"[1] Conectando a {VPS_HOST} como {VPS_USER}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

    try:
        if VPS_SSH_KEY:
            print(f"  Usando clave SSH: {VPS_SSH_KEY}")
            ssh.connect(
                VPS_HOST,
                port=22,
                username=VPS_USER,
                key_filename=VPS_SSH_KEY,
                timeout=15,
                allow_agent=False,
                look_for_keys=False,
                missing_host_key_policy=lambda x: None,
            )
        else:
            print("  Usando autenticación por password.")
            ssh.connect(
                VPS_HOST,
                port=22,
                username=VPS_USER,
                password=VPS_SSH_PASS,
                timeout=15,
            )
        print("  Conectado!")
    except paramiko.SSHException as e:
        print(f"  ERROR: {e}")
        print("  NOTA: Si es la primera conexión, configure StrictHostKeyChecking=no o use SSH key.")
        return 1
    except Exception as e:
        print(f"  ERROR: {e}")
        return 1

    try:
        # Verificar estructura actual
        print("[2] Verificando estructura actual...")
        stdin, stdout, stderr = ssh.exec_command(
            "ls -la /opt/ai-platform/Documents/AI-Platform/infra/docker/ 2>&1"
        )
        output = stdout.read().decode()
        if output.strip():
            for line in output.split("\n"):
                print(f"    {line}")

        # Corregir estructura
        print("[3] Corrigiendo estructura...")
        fix_cmd = f"""
cd /opt/ai-platform
mkdir -p infra/docker
if [ -d Documents/AI-Platform/infra/docker ]; then
    find Documents/AI-Platform/infra/docker -type f -exec cp {{}} infra/docker/ \\;
    rm -rf Documents
fi
echo "Archivos en infra/docker después del movimiento:"
ls -la infra/docker/
"""
        stdin, stdout, stderr = ssh.exec_command(fix_cmd)
        output = stdout.read().decode()
        error = stderr.read().decode()
        for line in output.split("\n"):
            if line.strip():
                print(f"    {line}")
        for line in error.split("\n"):
            if line.strip():
                print(f"    ERR: {line}")

        # Verificar resultado final
        print("[4] Verificación final...")
        stdin, stdout, stderr = ssh.exec_command("ls -la /opt/ai-platform/infra/docker/")
        output = stdout.read().decode()
        error = stderr.read().decode()
        for line in output.split("\n"):
            if line.strip():
                print(f"    {line}")
        for line in error.split("\n"):
            if line.strip():
                print(f"    ERR: {line}")

    finally:
        ssh.close()

    print()
    print("  !Hecho!")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
