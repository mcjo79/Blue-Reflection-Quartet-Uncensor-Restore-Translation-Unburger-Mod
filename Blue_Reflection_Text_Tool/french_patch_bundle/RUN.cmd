@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Choose the Python launcher that is available.
set "PY=python"
where py >nul 2>nul && set "PY=py -3"

if "%~1"=="" (
  rem Interactive mode: choose the game and the translation to install.
  %PY% br_french_installer.py
  goto :end
)

rem Advanced / direct mode: pass every argument to the 2017 patch tool.
%PY% br_french_patch.py %*
goto :end

:end
endlocal
exit /b %ERRORLEVEL%
