@echo off
rem Starts the three ADA-ELM processes, each in its own window. OnlyOffice (Docker) and MySQL must already be running.
cd /d "%~dp0"
start "ADA-ELM backend" cmd /c start-backend.bat
rem give the backend time to create/upgrade tables before the worker starts
timeout /t 8 /nobreak >nul
start "ADA-ELM worker" cmd /c start-worker.bat
start "ADA-ELM frontend" cmd /c start-frontend.bat
echo ADA-ELM is starting. Open http://localhost:8088 (or the ELM_WEB_PORT in .env).
timeout /t 5 >nul
