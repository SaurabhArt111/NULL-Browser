@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Running first-time setup...
    call "%~dp0setup_and_run.bat"
    exit /b %errorlevel%
)

echo Starting project...
powershell -NoProfile -Command "Start-Process -FilePath '%~dp0Search_Engine\Null Search Engine\run_engine.bat' -WorkingDirectory '%~dp0Search_Engine\Null Search Engine' | Out-Null"
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "Start-Process -FilePath '%~dp0Search_Engine\Null Browser\run_browser.bat' -WorkingDirectory '%~dp0Search_Engine\Null Browser' | Out-Null"
