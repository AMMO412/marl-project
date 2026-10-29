@echo off
cd /d "%~dp0.."
py -3.14 planning_middle_demo\workbench_server.py --open
if errorlevel 1 pause
