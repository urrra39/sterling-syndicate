# The Sterling Syndicate — local start (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== The Sterling Syndicate — local start ===" -ForegroundColor Cyan

$py = Join-Path $PSScriptRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Creating backend venv..."
  python -m venv (Join-Path $PSScriptRoot "backend\.venv")
}

& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install --only-binary=:all: greenlet==3.1.1
& $py -m pip install -r (Join-Path $PSScriptRoot "backend\requirements.txt")

if (Get-Command docker -ErrorAction SilentlyContinue) {
  Write-Host "Starting Postgres (sterling-db)..."
  docker compose up -d db
} else {
  Write-Host "Docker not found — ensure Postgres is on localhost:5432" -ForegroundColor Yellow
}

$env:DATABASE_URL = "postgresql+psycopg://sterling:change_me_strong_password@localhost:5432/sterling"
$env:JWT_SECRET_KEY = "dev-local-secret-key-change-before-prod-32c"
$env:CORS_ORIGINS = "http://localhost:5173"
$env:SANDBOX_ALLOW_SUBPROCESS_FALLBACK = "true"
$env:SECRETS_SCRUBBER_ENABLED = "true"
$env:ENVIRONMENT = "development"

Write-Host "Starting API :8000 ..."
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$PSScriptRoot\backend'; `$env:DATABASE_URL='$env:DATABASE_URL'; `$env:JWT_SECRET_KEY='$env:JWT_SECRET_KEY'; `$env:CORS_ORIGINS='$env:CORS_ORIGINS'; `$env:SANDBOX_ALLOW_SUBPROCESS_FALLBACK='true'; `$env:SECRETS_SCRUBBER_ENABLED='true'; & '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
)

Write-Host "Starting UI :5173 ..."
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$PSScriptRoot\frontend'; npm run dev -- --host 0.0.0.0 --port 5173"
)

Write-Host ""
Write-Host "UI  http://localhost:5173"
Write-Host "API http://localhost:8000/health"
