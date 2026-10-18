@echo off
setlocal
cd /d "%~dp0"
echo Mind Bloom setup (Python 3.12 recommended)
py -3.12 -m venv .venv
if errorlevel 1 (
  echo ERROR: Install Python 3.11 from https://www.python.org/downloads/release/python-31111/ and retry.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Setup complete. Edit .env, then run run.bat.
pause
