@echo off
setlocal
cd /d "%~dp0"
title Null Browser setup

set "VENV=%~dp0.venv"
set "PYEXE=%VENV%\Scripts\python.exe"

if not exist "%PYEXE%" (
    echo [1/3] Creating virtual environment in .venv ...
    where py >nul 2>nul
    if %errorlevel%==0 ( py -3 -m venv "%VENV%" ) else ( python -m venv "%VENV%" )
    if not exist "%PYEXE%" goto :nopython
)

echo [2/3] Installing dependencies (first run takes a few minutes) ...
"%PYEXE%" -m pip install --upgrade pip >nul 2>nul
"%PYEXE%" -m pip install -r "Search_Engine\Null Browser\requirements.txt" -r "Search_Engine\Null Search Engine\requirements.txt"
if errorlevel 1 goto :fail

echo [3/3] Starting Null Browser ...
call "%~dp0run_browser.bat"
exit /b 0

:nopython
echo.
echo Python 3.10 - 3.13 was not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH", then run this file again.
pause
exit /b 1

:fail
echo.
echo Dependency installation failed. Check your internet connection and run this file again.
pause
exit /b 1
