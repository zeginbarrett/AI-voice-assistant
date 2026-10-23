@echo off
setlocal
cd /d "%~dp0"
title SAM - Start PC without reflashing
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_bridge.ps1"
if errorlevel 1 pause
