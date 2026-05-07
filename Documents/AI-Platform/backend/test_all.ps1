# Script para iniciar servidor en segundo plano y verificar
Import-Module PSLocalServer -Force -ErrorAction SilentlyContinue

Write-Host "=== INICIANDO SERVIDOR ===" -ForegroundColor Cyan
Start-Process -NoNewWindow -FilePath "py" -ArgumentList "-m", "uvicorn", "ai_platform.main:app", "--host", "0.0.0.0", "--port", "4000"

Write-Host "Esperando 3 segundos..."
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "=== VERIFICANDO ENDPOINTS ===" -ForegroundColor Cyan
$tests = @(
    @{Name="Ping"; Uri="http://localhost:4000/api/v1/ping"},
    @{Name="Health"; Uri="http://localhost:4000/api/v1/health"},
    @{Name="Docs"; Uri="http://localhost:4000/docs"}
)

$allPassed = $true
foreach ($test in $tests) {
    try {
        $response = Invoke-RestMethod -Uri $test.Uri -UseBasicParsing
        $status = "PASSED"
        Write-Host "$($test.Name) - $status" -ForegroundColor Green
    } catch {
        Write-Host "$($test.Name) - FAILED: $($_.Exception.Message)" -ForegroundColor Red
        $allPassed = $false
    }
}

Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
if ($allPassed) {
    Write-Host "EL SERVIDOR ESTÁ CORRIENDO CORRECTAMENTE" -ForegroundColor Green
    Write-Host "Swagger UI: http://localhost:4000/docs" -ForegroundColor Cyan
    Write-Host "Para detener: Stop-Process -Name py -Force" -ForegroundColor Yellow
} else {
    Write-Host "ALGÚN ENDPOINT NO FUNCIONA" -ForegroundColor Red
}
Write-Host "===========================================" -ForegroundColor Cyan
