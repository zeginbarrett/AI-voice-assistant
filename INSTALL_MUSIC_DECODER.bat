@echo off
setlocal
cd /d "%~dp0"
title SAM - Install SD Music Decoder (NO FLASH)
if not exist "windows\python_path.txt" (
 echo Please first run RUN_SAM_TEST.bat so SAM can locate its working Python.
 pause
 exit /b 1
)
set /p SAM_PYTHON=<"windows\python_path.txt"
"%SAM_PYTHON%" "%~dp0windows\install_ffmpeg.py"
if errorlevel 1 (
 echo FFmpeg installation was unsuccessful. Check Internet connectivity.
) else (
 echo FFmpeg ready. Start SAM again with START_SAM.bat.
)
pause
