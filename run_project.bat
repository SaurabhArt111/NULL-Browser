@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Running first-time setup...
    call "%~dp0setup_and_run.bat"
    exit /b %errorlevel%
)

echo Starting project...
start "" "%~dp0Search_Engine\Null Search Engine\run_engine.bat"
timeout /t 3 /nobreak >nul
start "" "%~dp0Search_Engine\Null Browser\run_browser.bat"
