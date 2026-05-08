# ============================================================
# Script de Despliegue en VPS via SSH (PowerShell)
# ============================================================
# Ejecutar este script en PowerShell:
#   cd C:\Users\Jesús Díaz\Documents\AI-Platform
#   powershell -NoProfile -ExecutionPolicy Bypass -File deploy-vps.ps1
#
# Variables de entorno requeridas:
#   VPS_HOST     - IP o dominio del VPS (ej: "your-vps-ip-here")
#   VPS_USER     - Usuario SSH (ej: "root" o "deploy")
#   VPS_SSH_KEY  - Ruta al archivo de clave SSH privada
#   VPS_SSH_PASS - Password SSH (alternativa a VPS_SSH_KEY)
#   REPO_URL     - URL del repositorio (opcional, default: GitHub)
# ============================================================

param(
    [string]$VpsHost = $env:VPS_HOST,
    [int]$Port = 22,
    [string]$User = $env:VPS_USER,
    [string]$SshKey = $env:VPS_SSH_KEY,
    [string]$SshPass = $env:VPS_SSH_PASS,
    [string]$RepoUrl = $env:REPO_URL
)

# Validar variables de entorno requeridas
if (-not $VpsHost) {
    Write-Host "ERROR: VPS_HOST no está configurado." -ForegroundColor Red
    Write-Host "Configura la variable de entorno: $env:VPS_HOST" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Opciones:" -ForegroundColor Cyan
    Write-Host "  1. Set-Item -Path env:VPS_HOST -Value 'tu-vps-ip'" -ForegroundColor Gray
    Write-Host "  2. Pasar como parametro: -VpsHost 'tu-vps-ip'" -ForegroundColor Gray
    Write-Host ""
    exit 1
}

if (-not $User) {
    Write-Host "ERROR: VPS_USER no está configurado." -ForegroundColor Red
    Write-Host "Configura la variable de entorno: $env:VPS_USER" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Opciones:" -ForegroundColor Cyan
    Write-Host "  1. Set-Item -Path env:VPS_USER -Value 'deploy'" -ForegroundColor Gray
    Write-Host "  2. Pasar como parametro: -User 'deploy'" -ForegroundColor Gray
    Write-Host ""
    exit 1
}

# Validar autenticación (clave o password)
if (-not $SshKey -and -not $SshPass) {
    Write-Host "ERROR: Necesitas configurar VPS_SSH_KEY o VPS_SSH_PASS." -ForegroundColor Red
    Write-Host "Se recomienda usar clave SSH (VPS_SSH_KEY) por seguridad." -ForegroundColor Yellow
    exit 1
}

if (-not $RepoUrl) {
    $RepoUrl = $env:GITHUB_REPO_URL
    if (-not $RepoUrl) {
        $RepoUrl = "https://github.com/Jemadiar1/ai-platform.git"
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI Platform - Despliegue en VPS" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Función para ejecutar comandos SSH con clave
function Invoke-SSHKeyCommand {
    param(
        [string]$Command,
        [string]$Ip,
        [int]$Port,
        [string]$User,
        [string]$KeyPath
    )

    $sshArgs = @(
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=$null",
        "-i", $KeyPath,
        "-p", $Port,
        "${User}@${Ip}",
        $Command
    )

    $result = ssh @sshArgs 2>&1
    return $result
}

# Función para ejecutar comandos SSH con password
function Invoke-SSHPassCommand {
    param(
        [string]$Command,
        [string]$Ip,
        [int]$Port,
        [string]$User,
        [string]$Password
    )

    $securePass = ConvertTo-SecureString $Password -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential($User, $securePass)

    try {
        $result = Invoke-Command -ComputerName $Ip -Port $Port -Credential $cred -ScriptBlock {
            using namespace System.Management.Automation
            param($cmd)
            & $cmd
        } -ArgumentList $Command -ErrorAction SilentlyContinue

        return $result
    } catch {
        Write-Host "  SSH password auth failed: $_" -ForegroundColor Red
        return $null
    }
}

# Función unificada para ejecutar comandos SSH
function Invoke-SSHCommand {
    param(
        [string]$Command,
        [string]$Ip,
        [int]$Port,
        [string]$User,
        [string]$KeyPath,
        [string]$Password
    )

    if ($KeyPath) {
        return Invoke-SSHKeyCommand -Command $Command -Ip $Ip -Port $Port -User $User -KeyPath $KeyPath
    } else {
        return Invoke-SSHPassCommand -Command $Command -Ip $Ip -Port $Port -User $User -Password $Password
    }
}

# Paso 1: Verificar conectividad
Write-Host "[1/6] Verificando conexión al VPS ($VpsHost)..." -ForegroundColor Yellow
$pingResult = Test-Connection -ComputerName $VpsHost -Count 2 -Quiet -ErrorAction SilentlyContinue

if (-not $pingResult) {
    Write-Host "  Warning: Ping falló, intentando anyway..." -ForegroundColor Yellow
} else {
    Write-Host "  OK - Conectado" -ForegroundColor Green
}

# Paso 2: Clonar/clonar repositorio
Write-Host "[2/6] Clonando repositorio en /opt/ai-platform..." -ForegroundColor Yellow
try {
    $sshResult = Invoke-SSHCommand `
        -Command "cd /opt && (test -d ai-platform && cd ai-platform && git pull || git clone $RepoUrl)" `
        -Ip $VpsHost -Port $Port -User $User -KeyPath $SshKey -Password $SshPass

    if ($sshResult) {
        Write-Host "  OK - Repositorio listo" -ForegroundColor Green
    } else {
        Write-Host "  Warning: No se pudo conectar por SSH. Despliegue manual requerido." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Despliegue manual:" -ForegroundColor Cyan
        Write-Host "    1. ssh $User@$VpsHost" -ForegroundColor Gray
        Write-Host "    2. cd /opt && git clone $RepoUrl" -ForegroundColor Gray
        Write-Host "    3. cd ai-platform/infra/docker" -ForegroundColor Gray
        Write-Host "    4. cp .env.example .env && nano .env" -ForegroundColor Gray
        Write-Host "    5. docker compose -f docker-compose.prod.yml build && docker compose -f docker-compose.prod.yml up -d" -ForegroundColor Gray
        Write-Host ""
    }
} catch {
    Write-Host "  Warning: SSH falló. Despliegue manual requerido." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Despliegue manual:" -ForegroundColor Cyan
    Write-Host "    1. ssh $User@$VpsHost" -ForegroundColor Gray
    Write-Host "    2. cd /opt && git clone $RepoUrl" -ForegroundColor Gray
    Write-Host "    3. cd ai-platform/infra/docker" -ForegroundColor Gray
    Write-Host "    4. cp .env.example .env && nano .env" -ForegroundColor Gray
    Write-Host "    5. docker compose -f docker-compose.prod.yml build && docker compose -f docker-compose.prod.yml up -d" -ForegroundColor Gray
    Write-Host ""
}

# Paso 3: Preparar archivos de configuración
Write-Host "[3/6] Preparando archivos de configuración..." -ForegroundColor Yellow
Write-Host "  Asegúrate de copiar .env.example a .env en el VPS" -ForegroundColor Gray
Write-Host "  y completar las variables críticas: SECRET_KEY, CLERK_SECRET_KEY, OPENROUTER_API_KEY" -ForegroundColor Gray

# Paso 4: Verificar Docker
Write-Host "[4/6] Verificando Docker..." -ForegroundColor Yellow
try {
    $dockerResult = Invoke-SSHCommand `
        -Command "docker --version && docker compose version" `
        -Ip $VpsHost -Port $Port -User $User -KeyPath $SshKey -Password $SshPass

    if ($dockerResult) {
        Write-Host "  OK - Docker funcionando" -ForegroundColor Green
    }
} catch {
    Write-Host "  Warning: No se pudo verificar Docker via SSH" -ForegroundColor Yellow
}

# Paso 5: Desplegar
Write-Host "[5/6] Construyendo imagen y levantando servicios..." -ForegroundColor Yellow
Write-Host "  docker compose -f /opt/ai-platform/infra/docker/docker-compose.prod.yml build" -ForegroundColor Gray
Write-Host "  docker compose -f /opt/ai-platform/infra/docker/docker-compose.prod.yml up -d" -ForegroundColor Gray

# Paso 6: Verificación
Write-Host "[6/6] Verificación" -ForegroundColor Yellow
Write-Host "  docker compose -f /opt/ai-platform/infra/docker/docker-compose.prod.yml ps" -ForegroundColor Gray
Write-Host "  curl http://localhost:4000/api/v1/health" -ForegroundColor Gray

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Despliegue Manual Requerido" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Debido a limitaciones del entorno Windows," -ForegroundColor Gray
Write-Host "  ejecuta manualmente estos pasos:" -ForegroundColor Gray
Write-Host ""
Write-Host "  1. ssh $User`@$VpsHost" -ForegroundColor White
Write-Host "  2. cd /opt/ai-platform/infra/docker" -ForegroundColor White
Write-Host "  3. cp .env.example .env" -ForegroundColor White
Write-Host "  4. nano .env (completar claves)" -ForegroundColor White
Write-Host "  5. docker compose -f docker-compose.prod.yml build" -ForegroundColor White
Write-Host "  6. docker compose -f docker-compose.prod.yml up -d" -ForegroundColor White
Write-Host "  7. docker compose -f docker-compose.prod.yml ps" -ForegroundColor White
Write-Host "  8. curl http://localhost:4000/api/v1/health" -ForegroundColor White
Write-Host ""
