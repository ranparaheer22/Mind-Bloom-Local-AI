@echo off
setlocal
cd /d "%~dp0"
echo Mind Bloom Local AI Bridge setup
py -3.11 -m venv .venv
if errorlevel 1 (
  echo ERROR: Install Python 3.11 and enable the Python launcher, then retry.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Setup complete. Edit ai_service\.env and set SERVICE_TOKEN to a long random secret.
pause
