@echo off
setlocal
cd /d "%~dp0"
title SAM - Windows Control Center
set "SAM_PY="
if exist "windows\python_path.txt" set /p SAM_PY=<"windows\python_path.txt"
if defined SAM_PY if exist "%SAM_PY%" ("%SAM_PY%" "windows\sam_control_center.py" & goto finish)
where py >nul 2>nul && (py -3 "windows\sam_control_center.py" & goto finish)
python "windows\sam_control_center.py"
:finish
if errorlevel 1 pause
