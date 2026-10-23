@echo off
setlocal
cd /d "%~dp0"
set "POWERSHELL_TELEMETRY_OPTOUT=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_clone.ps1"
if errorlevel 1 (
  echo.
  echo Installation was not completed. Your previous SAM voice is unchanged.
)
echo.
pause
