@echo off
cd /d "%~dp0"

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10 or newer must be installed and on PATH.
        pause
        exit /b 1
    )

    echo Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Python 3.10 or newer is required. Install Python and re-run this script.
        pause
        exit /b 1
    )
)

if not exist "%VENV_PYTHON%" (
    echo Virtual environment was not created successfully.
    pause
    exit /b 1
)

echo Installing project dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip
"%VENV_PYTHON%" -m pip install -r "%~dp0Search_Engine\Null Search Engine\requirements.txt"
"%VENV_PYTHON%" -m pip install -r "%~dp0Search_Engine\Null Browser\requirements.txt"

echo Starting Null Search Engine...
start "" "%~dp0Search_Engine\Null Search Engine\run_engine.bat"

timeout /t 3 /nobreak >nul

echo Starting Null Browser...
start "" "%~dp0Search_Engine\Null Browser\run_browser.bat"

echo Both applications were started in separate windows.
