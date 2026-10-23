@echo off
rem Old name, kept so existing shortcuts keep working.
call "%~dp0run_null_browser.bat" %*
exit /b %errorlevel%
