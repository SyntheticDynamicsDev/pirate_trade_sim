@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo No local virtual environment found.
    echo Run install_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main.py
