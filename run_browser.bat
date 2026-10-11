@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    call "%~dp0setup_and_run.bat"
    exit /b
)
rem Starts Null Browser without a console window. The local Null Search server is started by the browser itself.
start "" ".venv\Scripts\pythonw.exe" "Search_Engine\Null Browser\main.py" %*
