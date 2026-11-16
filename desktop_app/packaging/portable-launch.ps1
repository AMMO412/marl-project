param([switch]$CheckOnly)
$ErrorActionPreference='Stop'
try {
    if(![Environment]::Is64BitOperatingSystem){throw '本软件需要 64 位 Windows。'}
    $packageRoot=$PSScriptRoot
    Set-Location -LiteralPath $packageRoot
    $netRelease=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release -ErrorAction SilentlyContinue).Release
    if(!$netRelease -or $netRelease -lt 528040){throw '请先安装 prerequisites\ndp48-x86-x64-allos-enu.exe，完成后重新启动软件。'}
    function WebView-Version {
        foreach($key in @('HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}','HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')) {
            $value=(Get-ItemProperty -LiteralPath $key -Name pv -ErrorAction SilentlyContinue).pv
            if($value -and [version]$value -gt [version]'0.0.0.0'){return $value}
        }
        return $null
    }
    $webview=WebView-Version
    if(!$webview) {
        if($CheckOnly){throw '尚未安装 WebView2，正常启动时可使用随包离线安装程序补齐。'}
        Write-Host '首次启动：正在安装地图浏览器运行环境，请稍候…'
        $installer=Join-Path $packageRoot 'prerequisites\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
        $installed=Start-Process -FilePath $installer -ArgumentList '/silent','/install' -WindowStyle Hidden -PassThru -Wait
        $webview=WebView-Version
        if(!$webview){throw "WebView2 安装未完成（退出码 $($installed.ExitCode)），请手动运行 prerequisites 中的 WebView2 安装程序。"}
    }
    $python=Join-Path $packageRoot 'runtime\python.exe'
    if(!(Test-Path -LiteralPath $python)){throw '随包 Python 缺失，请先完整解压压缩包。'}
    & $python -B -c 'import sys,workbench_server;print(sys.version);print(workbench_server.ROOT)'
    if($LASTEXITCODE -ne 0){throw '运行环境检查失败，请完整解压软件。'}
    if($CheckOnly){Write-Host "环境检查通过；WebView2 $webview";exit 0}
    Start-Process -FilePath (Join-Path $packageRoot 'MARL界面预览.exe') -WorkingDirectory $packageRoot -WindowStyle Hidden
}catch {Write-Host $_.Exception.Message -ForegroundColor Red;exit 1}
