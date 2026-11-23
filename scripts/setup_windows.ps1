$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location "$Root\backend"
if (-not (Test-Path .venv)) { python -m venv .venv }
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Write-Host "Backend ready. Review backend\.env, then run scripts\verify_windows.ps1." -ForegroundColor Green
Set-Location "$Root\frontend"
npm install
Write-Host "Frontend dependencies installed." -ForegroundColor Green
