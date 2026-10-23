@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
rem Uses the environment fix_qt_blocked.bat prepared, otherwise the project's own .venv.
set "PYFILE=%LOCALAPPDATA%\NullBrowser\python.txt"
if exist "%PYFILE%" (
    set /p NBPY=<"%PYFILE%"
    call "!NBPY!" main.py %*
    exit /b
)
if exist "..\..\.venv\Scripts\python.exe" (
    "..\..\.venv\Scripts\python.exe" main.py %*
    exit /b
)
echo No environment found. Run fix_qt_blocked.bat ^(it installs everything Null Browser needs^), or setup_and_run.bat in the project root.
pause
