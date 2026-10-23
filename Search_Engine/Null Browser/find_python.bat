@echo off
rem Finds a Python that can really load Qt and sets NB_PY (python.exe) and NB_PYW (pythonw.exe, no console window).
rem Call it from a script that has EnableDelayedExpansion on:   call "%~dp0find_python.bat"   then   if errorlevel 1 ...
rem Order: the environment setup_and_run.bat prepared in your user profile, then the project's own .venv.
set "NB_PY="
set "NB_PYW="
set "NB_HERE=%~dp0"
set "NB_CAND="
if exist "%LOCALAPPDATA%\NullBrowser\python.txt" set /p NB_CAND=<"%LOCALAPPDATA%\NullBrowser\python.txt"
if defined NB_CAND if exist "!NB_CAND!" "!NB_CAND!" "!NB_HERE!tools\qt_check.py" --quiet && set "NB_PY=!NB_CAND!"
if not defined NB_PY if exist "!NB_HERE!..\..\.venv\Scripts\python.exe" "!NB_HERE!..\..\.venv\Scripts\python.exe" "!NB_HERE!tools\qt_check.py" --quiet && set "NB_PY=!NB_HERE!..\..\.venv\Scripts\python.exe"
if not defined NB_PY exit /b 1
set "NB_PYW=!NB_PY:python.exe=pythonw.exe!"
if not exist "!NB_PYW!" set "NB_PYW=!NB_PY!"
exit /b 0
