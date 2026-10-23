@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "HERE=%~dp0"
cd /d "!HERE!"
title Null Browser
call "!HERE!find_python.bat"
if errorlevel 1 (
    echo Null Browser is not set up on this PC yet - running the one-time setup first...
    call "!HERE!..\..\setup_and_run.bat" --no-run
    call "!HERE!find_python.bat"
)
if not defined NB_PY (
    echo.
    echo Setup did not finish, so there is nothing to start. See the messages above ^(docs\WINDOWS_BLOCKED.md explains the Windows block^).
    pause
    exit /b 1
)
"!NB_PY!" main.py %*
set "CODE=!errorlevel!"
if not "!CODE!"=="0" (
    echo.
    echo Null Browser stopped with code !CODE!. The messages above and the log folder in %%APPDATA%%\NullBrowser say why.
    pause
)
exit /b !CODE!
