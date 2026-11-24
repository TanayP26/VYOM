$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$Root\backend'; .\.venv\Scripts\Activate.ps1; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$Root\frontend'; npm run dev"
Write-Host "VYOM launching: UI http://localhost:5173 | API http://localhost:8000/docs" -ForegroundColor Cyan
