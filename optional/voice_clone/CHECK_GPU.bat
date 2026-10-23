@echo off
setlocal
cd /d "%~dp0"
echo =========================================================
echo SAM GPU INSPECTION - NO FIRMWARE CHANGES
 echo.
where nvidia-smi.exe >nul 2>nul
if not errorlevel 1 (
    nvidia-smi.exe --query-gpu=name,driver_version,memory.total --format=csv,noheader
) else (
    echo NVIDIA CUDA utilities not detected in PATH.
    echo Your GPU may be AMD/Intel, or its NVIDIA drivers may need updating.
)
echo.
powershell.exe -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | Format-Table -AutoSize"
echo.
pause
