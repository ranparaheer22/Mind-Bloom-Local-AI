@echo off
where cloudflared >nul 2>nul
if errorlevel 1 (
  echo cloudflared not found. Install Cloudflare Tunnel first.
  echo https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  pause
  exit /b 1
)
cloudflared tunnel --url http://localhost:7860
pause
