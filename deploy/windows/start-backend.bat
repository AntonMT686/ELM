@echo off
rem ADA-ELM backend API (FastAPI). Keep this window open; close it or press Ctrl+C to stop.
title ADA-ELM backend
cd /d "%~dp0..\..\backend"
if not exist .venv\Scripts\python.exe (echo Run deploy\windows\setup.ps1 first. & pause & exit /b 1)
.venv\Scripts\python.exe -m app.serve
pause
