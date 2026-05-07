# Iniciar servidor FastAPI en segundo plano
$proc = Start-Process -NoNewWindow -FilePath "py" `
    -ArgumentList "-m", "uvicorn", "ai_platform.main:app", "--host", "0.0.0.0", "--port", "4000", "--log-level", "info" `
    -PassThru

Write-Host "Server PID: $($proc.Id)"
Write-Host "Waiting 3 seconds..."
Start-Sleep -Seconds 3

# Verificar que responde
try {
    $response = Invoke-RestMethod -Uri "http://localhost:4000/api/v1/ping" -UseBasicParsing
    Write-Host "SUCCESS: $($response | ConvertTo-Json -Compress)"
} catch {
    Write-Host "FAILED: $_"
}

# Mantener el proceso
Write-Host "Server is running. PID: $($proc.Id)"
Write-Host "To stop: Stop-Process -Id $($proc.Id)"
