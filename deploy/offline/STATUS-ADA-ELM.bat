@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0elm.ps1" status
echo.
echo ---- recent logs ----
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0elm.ps1" logs
pause
