$ErrorActionPreference = 'Stop'
$taskApp = Join-Path $PSScriptRoot 'planning_middle_demo/workbench_server.py'
$taskPython = Get-Command python -ErrorAction SilentlyContinue
if ($taskPython) { & $taskPython.Source -X utf8 $taskApp --open --open-path '/?new=interop' }
else { & py -3 -X utf8 $taskApp --open --open-path '/?new=interop' }
exit $LASTEXITCODE
