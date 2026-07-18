@echo off
setlocal
cd /d "%~dp0"

echo === The Sterling Syndicate — local start ===

if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating backend venv...
  python -m venv backend\.venv
)

echo Ensuring greenlet binary wheel...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip >nul
backend\.venv\Scripts\python.exe -m pip install --only-binary=:all: greenlet==3.1.1
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

where docker >nul 2>&1
if %ERRORLEVEL%==0 (
  echo Starting Postgres via Docker...
  docker compose up -d db
) else (
  echo Docker not found — ensure Postgres is running on localhost:5432
)

echo Starting API on :8000 ...
start "Sterling API" cmd /k "cd /d %~dp0backend && set DATABASE_URL=postgresql+psycopg://sterling:change_me_strong_password@localhost:5432/sterling&& set JWT_SECRET_KEY=dev-local-secret-key-change-before-prod-32c&& set CORS_ORIGINS=http://localhost:5173&& set SANDBOX_ALLOW_SUBPROCESS_FALLBACK=true&& .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo Starting UI on :5173 ...
start "Sterling UI" cmd /k "cd /d %~dp0frontend && npm run dev -- --host 0.0.0.0 --port 5173"

echo.
echo Open http://localhost:5173  (API http://localhost:8000/health)
endlocal
