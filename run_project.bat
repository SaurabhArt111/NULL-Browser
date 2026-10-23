@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~dp0"
cd /d "!ROOT!"
title Null Browser project
call "!ROOT!Search_Engine\Null Browser\find_python.bat"
if errorlevel 1 (
    echo This PC has not been set up yet - running the one-time setup first...
    call "!ROOT!setup_and_run.bat" --no-run
    call "!ROOT!Search_Engine\Null Browser\find_python.bat"
)
if not defined NB_PY (
    echo.
    echo Setup did not finish, so nothing was started.
    pause
    exit /b 1
)
"!NB_PY!" -c "import uvicorn, fastapi" >nul 2>nul
if errorlevel 1 (
    echo The search server's packages are not installed - starting the browser only. Run setup_and_run.bat to add them.
) else (
    echo Starting Null Search Engine in its own minimized window...
    start "Null Search Engine" /min /d "!ROOT!Search_Engine\Null Search Engine" "!NB_PY!" -u src\main.py
    timeout /t 3 /nobreak >nul
)
echo Starting Null Browser...
call "!ROOT!Search_Engine\Null Browser\run_null_browser.bat" %*
exit /b !errorlevel!
