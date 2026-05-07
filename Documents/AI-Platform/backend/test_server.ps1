# Script para iniciar servidor y verificar
Start-Process -NoNewWindow -FilePath "py" -ArgumentList "-m", "uvicorn", "ai_platform.main:app", "--host", "0.0.0.0", "--port", "4000"
Start-Sleep -Seconds 3
try {
    $r = Invoke-RestMethod -Uri "http://localhost:4000/api/v1/ping"
    Write-Host "SUCCESS: $($r | ConvertTo-Json -Compress)"
} catch {
    Write-Host "FAILED: $_"
}
