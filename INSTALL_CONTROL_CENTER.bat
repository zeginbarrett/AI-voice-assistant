@echo off
setlocal
cd /d "%~dp0"
title SAM Control Center - Setup
where py >nul 2>nul && (py -3 INSTALL_SAM_CONTROL_CENTER.py & goto done)
where python >nul 2>nul && (python INSTALL_SAM_CONTROL_CENTER.py & goto done)
if exist "windows\python_path.txt" (
 set /p SAM_PY=<"windows\python_path.txt"
 if exist "%SAM_PY%" ("%SAM_PY%" INSTALL_SAM_CONTROL_CENTER.py & goto done)
)
echo Python not available. Run RUN_SAM_TEST.bat first to install SAM.
:done
pause
