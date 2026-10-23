@echo off
title Tim Cheese Scanner
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)

%PY% --version >nul 2>nul
if not %errorlevel%==0 (
    echo Python is not installed.
    echo Install it from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
    echo or run:  winget install Python.Python.3.12
    pause
    exit /b 1
)

%PY% -c "import serial" >nul 2>nul
if not %errorlevel%==0 (
    echo Installing pyserial...
    %PY% -m pip install --user pyserial
)

%PY% scanner.py %*
echo.
pause
