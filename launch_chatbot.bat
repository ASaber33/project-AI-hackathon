@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=python"
if exist "%~dp0venv\Scripts\python.exe" set "PYTHON=%~dp0venv\Scripts\python.exe"
if exist "%~dp0..\.venv\Scripts\python.exe" set "PYTHON=%~dp0..\.venv\Scripts\python.exe"

echo Starting Guideline AI...
start "Guideline AI Server" /b "%PYTHON%" app.py
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5001"

echo Guideline AI is running at http://127.0.0.1:5001
echo Close the server window to stop the chatbot.
pause
