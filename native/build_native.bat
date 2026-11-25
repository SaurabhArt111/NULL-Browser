@echo off
rem ============================================================================================================
rem  Builds Null Browser's own Rust ad-block module (Brave adblock-rust + PyO3) and installs it next to the browser.
rem
rem  Needs: Rust (https://rustup.rs) with the MSVC toolchain, the "Desktop development with C++" workload of the
rem         Visual Studio Build Tools (for link.exe), and the project's virtual environment (setup_and_run.bat).
rem
rem  Options (environment variables, all optional):
rem     NULL_NATIVE_CPU=native     tune for THIS processor only (fastest, not portable). Default: x86-64-v2, which every
rem                                PC that runs Windows 10 / 11 supports (SSE4.2 + POPCNT make the matcher faster).
rem     NULL_NATIVE_NOPAUSE=1      do not wait for a key at the end (for scripts / CI).
rem ============================================================================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "DEST=%ROOT%\Search_Engine\Null Browser\null_browser\_native"
set "DIST=%~dp0dist"
set "CPU=%NULL_NATIVE_CPU%"
if not defined CPU set "CPU=x86-64-v2"

echo [1/6] Checking the tools...
where cargo >nul 2>nul
if errorlevel 1 (
    echo   Rust was not found. Install it from https://rustup.rs ^(choose the default MSVC toolchain^) and run this again.
    echo   Nothing is lost: the browser already works with the "adblock" wheel or its built-in Python engine.
    goto :fail_nomsg
)
if not exist "%PY%" (
    echo   Virtual environment not found. Run setup_and_run.bat in the project root first.
    goto :fail_nomsg
)
rem link.exe comes with the Visual Studio Build Tools; without it cargo fails with a long, confusing error.
rem (rustc finds it through vswhere even when it is not on PATH, so both are checked. No parentheses blocks here:
rem  "%ProgramFiles(x86)%" would close them early.)
where link.exe >nul 2>nul && goto :msvc_ok
set "VSW=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSW%" goto :no_msvc
"%VSW%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | findstr /r "." >nul || goto :no_msvc
:msvc_ok
rustup target list --installed 2>nul | findstr /i "x86_64-pc-windows-msvc" >nul
if errorlevel 1 (
    echo   Adding the x86_64-pc-windows-msvc target...
    rustup target add x86_64-pc-windows-msvc || goto :fail
)
for /f "delims=" %%v in ('cargo --version') do echo   %%v
for /f "delims=" %%v in ('"%PY%" -c "import sys; print('Python', sys.version.split()[0])"') do echo   %%v

echo [2/6] Installing / updating maturin...
"%PY%" -m pip install --disable-pip-version-check --quiet --upgrade "maturin>=1.5,<2" || goto :fail

echo [3/6] Building (release, LTO, CPU level %CPU%) - the first build takes a few minutes...
if exist "%DIST%" del /q "%DIST%\null_adblock-*.whl" >nul 2>nul
set "RUSTFLAGS=-C target-cpu=%CPU%"
set "CARGO_INCREMENTAL=0"
pushd null_adblock
set "LOCKED="
if exist Cargo.lock set "LOCKED=--locked"
"%PY%" -m maturin build --release --strip %LOCKED% -i "%PY%" --out "%DIST%"
if errorlevel 1 (
    if defined LOCKED (
        echo   The locked dependency versions did not build; retrying with the newest compatible ones...
        "%PY%" -m maturin build --release --strip -i "%PY%" --out "%DIST%" || (popd & goto :fail)
    ) else (
        popd & goto :fail
    )
)
popd

echo [4/6] Installing into the browser...
set "WHEEL="
for /f "delims=" %%w in ('dir /b /o:d "%DIST%\null_adblock-*.whl" 2^>nul') do set "WHEEL=%DIST%\%%w"
if not defined WHEEL (
    echo   No wheel was produced.
    goto :fail
)
set "STAGE=%DEST%.new"
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"
rem a wheel is a zip file: unpack the compiled module into a staging folder first, so a failed step never leaves the
rem browser without a working engine
"%PY%" -I -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "%WHEEL%" "%STAGE%" || goto :fail

echo [5/6] Testing the new module...
"%PY%" -I -c "import sys; sys.path.insert(0, sys.argv[1]); import null_adblock as n; print('  engine', n.engine_version())" "%STAGE%" || goto :fail

echo [6/6] Activating it...
if exist "%DEST%" rmdir /s /q "%DEST%"
if exist "%DEST%" (
    echo   The old module is in use. Close Null Browser and run this script again.
    goto :fail_nomsg
)
move "%STAGE%" "%DEST%" >nul || goto :fail
if exist "%~dp0null_adblock\target\release\.fingerprint" echo   ^(build cache kept in native\null_adblock\target: the next build is much faster^)

echo.
echo Done. Null Browser uses the Rust engine from its next start (Settings ^> Privacy shows which engine is active).
call :pause
exit /b 0

:no_msvc
echo   The Microsoft C++ build tools were not found. Install "Build Tools for Visual Studio" with the
echo   "Desktop development with C++" workload: https://visualstudio.microsoft.com/visual-cpp-build-tools/
goto :fail_nomsg

:fail
echo.
echo Build failed (see the messages above).
:fail_nomsg
echo The browser keeps working with its other ad-block engines.
call :pause
exit /b 1

:pause
if not "%NULL_NATIVE_NOPAUSE%"=="1" pause
exit /b 0
