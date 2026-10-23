@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "HERE=%~dp0"
cd /d "!HERE!"
title Null Browser - build NullBrowser.exe
rem Builds dist\NullBrowser\NullBrowser.exe with PyInstaller (the engine behind auto-py-to-exe) from NullBrowser.spec.
rem See docs\BUILD_EXE.md. Run setup_and_run.bat once first: it installs everything the build bundles.
call "!HERE!find_python.bat"
if errorlevel 1 (
    echo Run setup_and_run.bat in the project folder first ^(it prepares the Python environment this build uses^).
    pause
    exit /b 1
)
"!NB_PY!" -c "import uvicorn, fastapi" >nul 2>nul
if errorlevel 1 (
    echo The search server's packages are missing from this environment, so the .exe would have no Null Search.
    echo Run setup_and_run.bat in the project folder to install them, then build again.
    pause
    exit /b 1
)
"!NB_PY!" -m pip install --disable-pip-version-check --upgrade pyinstaller tzdata || (echo Could not install PyInstaller. & pause & exit /b 1)
set "OUT=!HERE!..\..\dist"
"!NB_PY!" -m PyInstaller --noconfirm --clean --distpath "!OUT!" --workpath "!HERE!..\..\build" NullBrowser.spec
if errorlevel 1 (
    echo.
    echo The build failed - the messages above say why.
    pause
    exit /b 1
)
echo.
echo Done: "!OUT!\NullBrowser\NullBrowser.exe"
echo Copy or zip the whole NullBrowser folder - the .exe needs the files next to it.
set /p MAKELNK="Create Desktop and Start-menu shortcuts for it now? [y/N] "
if /i "!MAKELNK!"=="y" powershell -NoProfile -ExecutionPolicy Bypass -File "!HERE!tools\make_shortcut.ps1" -Exe "!OUT!\NullBrowser\NullBrowser.exe" -Browser "!HERE!."
pause
