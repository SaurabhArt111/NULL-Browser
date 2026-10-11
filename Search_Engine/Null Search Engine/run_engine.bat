@echo off
cd /d "%~dp0"
rem Optional: the browser starts this server automatically. Run it by hand to crawl / manage the index.
if exist "..\..\.venv\Scripts\python.exe" (
    "..\..\.venv\Scripts\python.exe" src\main.py
) else (
    echo Environment not found. Run setup_and_run.bat in the project root first.
    pause
)
