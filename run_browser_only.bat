@echo off
rem Starts only the browser. It starts its own local search server in the background, so there is no second window.
rem If this PC has not been set up yet, the one-time setup runs first.
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
call "%ROOT%Search_Engine\Null Browser\run_null_browser.bat" %*
exit /b %errorlevel%
