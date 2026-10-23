@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Null Browser - setup
rem One-time setup: a private Python environment in your user profile, with everything Null Browser needs. Then it starts the browser.
rem   setup_and_run.bat            set up (or repair) and start
rem   setup_and_run.bat --no-run   set up only
echo.
echo This script does NOT bypass or switch off any Windows security feature.
echo It installs Qt and the other packages into a private environment in your user profile ^(on C:^), using PyQt6 releases that many PCs
echo already run, and checks that Qt loads. If Windows still blocks Qt, it prints which file and which policy blocked it.
echo.
set "ROOT=%~dp0"
set "BROWSER=%~dp0Search_Engine\Null Browser"
set "ENGINE=%~dp0Search_Engine\Null Search Engine"
set "BASE=%LOCALAPPDATA%\NullBrowser"
set "NORUN="
if /i "%~1"=="--no-run" set "NORUN=1"
if not exist "%BASE%" mkdir "%BASE%"

rem ---- already prepared? ----------------------------------------------------------------------------------------------
call "%BROWSER%\find_python.bat"
if not errorlevel 1 goto :already

rem ---- find Python 3.10+ -----------------------------------------------------------------------------------------------
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
if defined PY goto :havepython
echo Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) or run:  winget install Python.Python.3.12
echo Then run this file again.
pause
exit /b 1

:havepython
rem ---- PyQt6 releases, newest first: the first one Windows lets through is used -------------------------------------------
call :try 6.9.1 6.9.0 && goto :ready
call :try 6.8.1 6.8.0 && goto :ready

echo.
echo ================================================================
echo Qt is still blocked or could not be installed. Details:
echo ================================================================
"!VENV!\Scripts\python.exe" "%BROWSER%\tools\qt_check.py"
echo.
echo Send the lines above to whoever manages this computer and ask them to allow the folder:
echo     %BASE%
echo See "%BROWSER%\docs\WINDOWS_BLOCKED.md".
pause
exit /b 1

:ready
echo !VENV!\Scripts\python.exe> "%BASE%\python.txt"
call "%BROWSER%\find_python.bat"
echo.
echo Qt loads. Creating the "Null Browser" shortcuts ^(Desktop and Start menu^)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%BROWSER%\tools\make_shortcut.ps1" -Python "!NB_PYW!" -Browser "%BROWSER%" >nul 2>nul || echo ^(shortcuts could not be created - start the browser with run_browser_only.bat^)
goto :done

:already
echo Null Browser is already set up ^(!NB_PY!^).

:done
if defined NORUN exit /b 0
echo.
echo Starting Null Browser. Next time use the "Null Browser" shortcut, run_browser_only.bat or run_project.bat.
call "%BROWSER%\run_null_browser.bat"
exit /b %errorlevel%

:try
set "VENV=%BASE%\venv-%~1"
echo.
echo ==== Trying PyQt6 %~1 / WebEngine %~2 in "!VENV!"
if not exist "!VENV!\Scripts\python.exe" %PY% -m venv "!VENV!" || exit /b 1
"!VENV!\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: "PyQt6==%~1" "PyQt6-WebEngine==%~2" imageio-ffmpeg || exit /b 1
"!VENV!\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: -r "%BROWSER%\requirements-optional.txt" || echo ^(optional Rust ad-block engine not installed: the built-in engine is used^)
"!VENV!\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%ENGINE%\requirements.txt" || echo ^(search server packages not installed: the browser works, Null Search is unavailable^)
"!VENV!\Scripts\python.exe" "%BROWSER%\tools\qt_check.py" || exit /b 1
exit /b 0
