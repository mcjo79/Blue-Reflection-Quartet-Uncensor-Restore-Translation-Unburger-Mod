@echo off
setlocal
cd /d "%~dp0"
rem General launcher. No argument: interactive shell. With arguments: run that command and exit.
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% br_launcher.py %*
exit /b %ERRORLEVEL%
