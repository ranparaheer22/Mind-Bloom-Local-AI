@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup_ai_service.bat first.
  pause
  exit /b 1
)
if not exist .env (
  copy .env.example .env
  echo Edit ai_service\.env and set SERVICE_TOKEN before starting.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 7860
pause
