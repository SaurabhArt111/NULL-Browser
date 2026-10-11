@echo off
cd /d "%~dp0"
if exist "..\..\.venv\Scripts\python.exe" (
    "..\..\.venv\Scripts\python.exe" main.py %*
) else (
    echo Environment not found. Run setup_and_run.bat in the project root first.
    pause
)
