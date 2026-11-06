@echo off
rem ADA-ELM background worker (SLA reminders, due dates). Keep this window open.
title ADA-ELM worker
cd /d "%~dp0..\..\backend"
if not exist .venv\Scripts\python.exe (echo Run deploy\windows\setup.ps1 first. & pause & exit /b 1)
.venv\Scripts\python.exe -m app.worker
pause
