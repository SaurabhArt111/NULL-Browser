@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Null Browser - Qt blocked by Windows
echo.
echo This script does NOT bypass or switch off any Windows security feature.
echo It (1) installs Qt into a private environment on your user profile (C:), using PyQt6 releases that many PCs already run,
echo and (2) if Windows still blocks Qt, prints which file and which policy blocked it, so you know what to ask your administrator.
echo.
set "BASE=%LOCALAPPDATA%\NullBrowser"
if not exist "%BASE%" mkdir "%BASE%"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python 3 was not found. Install Python 3.10 or newer from python.org ^(tick "Add to PATH"^), then run this again.
    pause
    exit /b 1
)

call :try 6.9.1 6.9.0 && goto :ok
call :try 6.8.1 6.8.0 && goto :ok

echo.
echo ================================================================
echo Qt is still blocked. Details from Windows:
echo ================================================================
"%VENV%\Scripts\python.exe" tools\qt_check.py
echo.
echo Send the lines above to whoever manages this computer and ask them to allow the folder:
echo     %BASE%
echo See docs\WINDOWS_BLOCKED.md.
pause
exit /b 1

:ok
echo %VENV%\Scripts\python.exe> "%BASE%\python.txt"
echo.
echo Qt loads. Starting Null Browser. Next time use run_null_browser.bat
"%VENV%\Scripts\python.exe" main.py %*
exit /b 0

:try
set "VENV=%BASE%\venv-%~1"
echo.
echo ==== Trying PyQt6 %~1 / WebEngine %~2 in "%VENV%"
if not exist "%VENV%\Scripts\python.exe" (
    %PY% -m venv "%VENV%" || exit /b 1
)
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: "PyQt6==%~1" "PyQt6-WebEngine==%~2" imageio-ffmpeg || exit /b 1
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: -r requirements-optional.txt || echo ^(optional Rust ad-block engine not installed: the built-in engine is used^)
"%VENV%\Scripts\python.exe" tools\qt_check.py || exit /b 1
exit /b 0
