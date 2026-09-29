@echo off
cd /d "%~dp0"
start "Null Search Engine" cmd /k "cd /d ""%~dp0Search_Engine\Null Search Engine"" && run_engine.bat"
start "Null Browser" cmd /k "cd /d ""%~dp0Search_Engine\Null Browser"" && run_browser.bat"
