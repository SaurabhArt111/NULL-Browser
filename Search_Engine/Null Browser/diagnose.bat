@echo off
cd /d "%~dp0"
set "PY=..\..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo Null Browser diagnostics - this takes a few minutes. Browser windows will open and close by themselves; please don't touch the mouse.
echo.
"%PY%" diagnose.py
echo.
pause
