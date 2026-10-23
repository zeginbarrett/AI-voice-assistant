@echo off
setlocal
cd /d "%~dp0"
title SAM V5 - Hands-free Conversations, Music and Voice Volume
color 0B
echo ============================================================
echo  SAM V5 - ONE CLICK FLASH AND START
 echo  Keeps the tested v4 microphone, adds microSD music,
echo  automatic follow-up conversations and voice volume commands.
echo ============================================================
echo.
echo Close the OLD SAM window first using Ctrl+C.
echo Plug your Waveshare into USB, then let this window run.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
 echo.
 echo Failed to compile/flash. See logs\compile.log and logs\flash.log
 pause
 exit /b 1
)
echo.
echo SAM V5 flashed. PC is listening for Hey Sam - no buttons.
echo Music needs a FAT32 microSD containing MP3 files.
echo For a new female voice, run CHOOSE_SAM_VOICE.bat later.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_bridge.ps1"
pause
