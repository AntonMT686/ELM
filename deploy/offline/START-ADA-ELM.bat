@echo off
REM ADA-ELM one-click start for the OFFLINE Windows server.
REM First run: verifies the package, loads images, asks 4 questions, generates secrets, starts everything.
setlocal
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting Administrator rights ^(needed once for the firewall rule^)...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0elm.ps1" start
echo.
pause
