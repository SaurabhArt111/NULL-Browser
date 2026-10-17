@echo off
rem Builds Null Browser's own Rust ad-block module (Brave adblock-rust + PyO3) and installs it next to the browser.
rem Needs: Rust (https://rustup.rs) and the project's virtual environment (setup_and_run.bat creates it).
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "DEST=%ROOT%\Search_Engine\Null Browser\null_browser\_native"

where cargo >nul 2>nul
if errorlevel 1 (
    echo Rust was not found. Install it from https://rustup.rs and run this script again.
    echo Nothing is lost: the browser already works with the "adblock" wheel or its built-in Python engine.
    pause
    exit /b 1
)
if not exist "%PY%" (
    echo Virtual environment not found. Run setup_and_run.bat in the project root first.
    pause
    exit /b 1
)

"%PY%" -m pip install --upgrade maturin || goto :fail
cd null_adblock
"%PY%" -m maturin build --release --out "%~dp0dist" || goto :fail
cd ..

if exist "%DEST%" rmdir /s /q "%DEST%"
mkdir "%DEST%"
rem a wheel is a zip file: unpack the compiled module into the browser's _native folder
"%PY%" -c "import glob,zipfile,sys; w=sorted(glob.glob(r'%~dp0dist\null_adblock-*.whl'))[-1]; zipfile.ZipFile(w).extractall(r'%DEST%'); print('installed', w)" || goto :fail

"%PY%" -I -c "import sys; sys.path.insert(0, r'%DEST%'); import null_adblock; print(null_adblock.engine_version())" || goto :fail
echo.
echo Done. Null Browser will use the Rust engine on its next start (Settings -> Privacy shows which engine is active).
pause
exit /b 0

:fail
echo.
echo Build failed. The browser keeps working with its other engines.
pause
exit /b 1
