@echo off
setlocal
cd /d "%~dp0"
title SAM - Choose Female Voice
if not exist "windows\python_path.txt" (
 echo Run RUN_SAM_TEST.bat first to install SAM.
 pause
 exit /b 1
)
set /p SAM_PYTHON=<"windows\python_path.txt"
"%SAM_PYTHON%" "%~dp0windows\choose_voice.py"
if errorlevel 1 echo Voice not changed.
pause
