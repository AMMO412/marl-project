@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py -3"
%PY% planning_middle_demo\workbench_server.py --open --open-path "/?new=interop"
if errorlevel 1 (
  echo.
  echo Workbench failed to start. Close any old Python server window and retry.
  pause
)
