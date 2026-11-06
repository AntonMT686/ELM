@echo off
rem ADA-ELM frontend web server (serves frontend\dist, forwards /api to the backend). Keep this window open.
rem For development with hot reload use:  cd frontend  and  npm run dev
title ADA-ELM frontend
cd /d "%~dp0..\..\frontend"
if not exist dist\index.html (echo Run deploy\windows\setup.ps1 first. & pause & exit /b 1)
call npm run serve
pause
