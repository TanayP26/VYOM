$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

Set-Location "$Root\backend"
& .\.venv\Scripts\python.exe -m pytest -q
Assert-LastExitCode "Backend test suite"

& .\.venv\Scripts\python.exe -m pip check
Assert-LastExitCode "Python dependency check"

& .\.venv\Scripts\python.exe -m compileall -q app
Assert-LastExitCode "Backend compile check"

Set-Location "$Root\frontend"
npm run build
Assert-LastExitCode "Frontend production build"

Write-Host "VYOM verification completed successfully." -ForegroundColor Green
