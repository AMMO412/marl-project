@echo off
setlocal
chcp 65001 >nul
title Planning Workbench
pushd "%~dp0.."
if errorlevel 1 goto failed
python --version >nul 2>&1
if not errorlevel 1 goto python
py -3 --version >nul 2>&1
if not errorlevel 1 goto launcher
echo Python 3 is required. Please install Python and add it to PATH.
goto failed
:python
python "planning_middle_demo\workbench_server.py" --open %*
goto finished
:launcher
py -3 "planning_middle_demo\workbench_server.py" --open %*
:finished
set "RESULT=%errorlevel%"
popd
if not "%RESULT%"=="0" goto failed
echo Workbench launcher finished. If the browser did not open, visit:
echo http://127.0.0.1:8766/
echo If a different port was printed above, use that address instead.
pause
exit /b 0
:failed
echo Workbench failed to start. See the error above.
pause
exit /b 1
