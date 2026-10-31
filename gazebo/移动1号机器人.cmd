@echo off
setlocal
py -3 "%~dp0local_preview\launch.py" drive
set "preview_exit=%errorlevel%"
if not "%preview_exit%"=="0" pause
exit /b %preview_exit%
