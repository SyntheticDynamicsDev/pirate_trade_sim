@echo off
setlocal

cd /d "%~dp0"

echo.
echo Installing Pirate Trade dependencies...
echo.

py -3 -m venv .venv
if errorlevel 1 (
    echo.
    echo Could not create Python virtual environment.
    echo Please install Python 3.11 or newer from https://www.python.org/downloads/
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo Installation complete. Start the game with run_game.bat
pause
