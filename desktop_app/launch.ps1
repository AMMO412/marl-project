$ErrorActionPreference = 'Stop'
try {
    $program = Join-Path $PSScriptRoot 'dist\MARL界面预览.exe'
    $activePath = Join-Path $PSScriptRoot 'dist\active-program.txt'
    if (Test-Path -LiteralPath $activePath) {
        $activeName = (Get-Content -LiteralPath $activePath -Encoding UTF8 -Raw).Trim()
        if ($activeName -eq [IO.Path]::GetFileName($activeName) -and $activeName.EndsWith('.exe')) {
            $activeProgram = Join-Path (Join-Path $PSScriptRoot 'dist') $activeName
            if (Test-Path -LiteralPath $activeProgram) { $program = $activeProgram }
        }
    }
    if (!(Test-Path -LiteralPath $program)) { throw '未找到软件，请先运行 desktop_app\build.cmd。' }
    if ($args.Count -gt 0) { & $program @args | Out-Null; exit $LASTEXITCODE }
    Start-Process -FilePath $program -WorkingDirectory (Split-Path -Parent $program)
} catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
