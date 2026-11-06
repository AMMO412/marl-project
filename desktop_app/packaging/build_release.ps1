$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent          # desktop_app
$repo = Split-Path $root -Parent                 # project root
$version = '0.5.0'
$release = Join-Path $root 'release\MARL界面预览'
$cache = Join-Path $root '.cache'
$pythonZip = Join-Path $cache 'python-3.14.7-embed-amd64.zip'

function Copy-Tree($src, $dst, $excludeNames) {
    New-Item -ItemType Directory -Force $dst | Out-Null
    Get-ChildItem $src -Force | Where-Object { $excludeNames -notcontains $_.Name } | ForEach-Object {
        $target = Join-Path $dst $_.Name
        if ($_.PSIsContainer) {
            Copy-Tree $_.FullName $target $excludeNames
        } else {
            Copy-Item $_.FullName $target -Force
        }
    }
}

if (Test-Path $release) { Remove-Item -Recurse -Force $release }
New-Item -ItemType Directory -Force $release | Out-Null

# 1. Desktop executable and WebView2 runtime.
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'build.ps1')
Copy-Item (Join-Path $root 'dist\MARL界面预览.exe') $release -Force
Copy-Item (Join-Path $root 'dist\*.dll') $release -Force
Copy-Item (Join-Path $root 'dist\WebView2-*.txt') $release -Force

# 2. Portable Python.
if (-not (Test-Path $pythonZip)) {
    Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip' -OutFile $pythonZip -UseBasicParsing
}
$runtime = Join-Path $release 'runtime'
New-Item -ItemType Directory -Force $runtime | Out-Null
Expand-Archive $pythonZip $runtime -Force
@('python314.zip', '.', '..\app\planning_middle_demo', '..\app', 'import site') |
    Set-Content (Join-Path $runtime 'python314._pth') -Encoding ASCII
New-Item -ItemType Directory -Force (Join-Path $release 'LICENSES') | Out-Null
Copy-Item (Join-Path $runtime 'LICENSE.txt') (Join-Path $release 'LICENSES\Python-LICENSE.txt') -Force
Copy-Item (Join-Path $root 'lib\webview2\LICENSE.txt') (Join-Path $release 'LICENSES\WebView2-LICENSE.txt') -Force
Copy-Item (Join-Path $root 'lib\webview2\NOTICE.txt') (Join-Path $release 'LICENSES\WebView2-NOTICE.txt') -Force

# 3. Application tree.
$app = Join-Path $release 'app'
$exclude = @('outputs', 'tests', '__pycache__', '.work', '.pytest_cache')
Copy-Tree (Join-Path $repo 'planning_middle_demo') (Join-Path $app 'planning_middle_demo') $exclude
Copy-Tree (Join-Path $repo 'configs') (Join-Path $app 'configs') @()
Copy-Tree (Join-Path $repo 'docs') (Join-Path $app 'docs') @()
Copy-Item (Join-Path $repo 'README.md') (Join-Path $app 'README.md') -Force
New-Item -ItemType Directory -Force (Join-Path $app '资料') | Out-Null
Copy-Tree (Join-Path $repo '资料\接口说明') (Join-Path $app '资料\接口说明') @()
Copy-Item (Join-Path $repo '资料\README.md') (Join-Path $app '资料\README.md') -Force

# 4. Sample runs so the first launch has real data.
$dataRuns = Join-Path $release 'data\runs'
New-Item -ItemType Directory -Force $dataRuns | Out-Null
$samples = Get-ChildItem (Join-Path $repo 'planning_middle_demo\outputs') -Directory |
    Where-Object { $_.Name -like 'workbench_20261106_*' } |
    Sort-Object LastWriteTime -Descending | Select-Object -First 2
foreach ($sample in $samples) {
    Copy-Tree $sample.FullName (Join-Path $dataRuns $sample.Name) @('.live_state.json', '.live_scene.json', '.live_request.json', '.live_reply.json')
}

# 5. Notes and checksums.
$readme = @"
MARL界面预览 v$version（本地可视化演示版）

启动：双击 MARL界面预览.exe。
数据：data\runs\ 下为随包样例；新运行也写入这里。
日志：logs\ 由程序创建。
运行时：runtime\ 为便携 Python；lib\webview2 为 WebView2 SDK。
边界：本软件是规划中间层的本地可视化演示，不是 ROS2/Gazebo/UE5 真实平台联调。
"@
Set-Content (Join-Path $release '启动说明.txt') $readme -Encoding UTF8
Set-Content (Join-Path $release 'VERSION.txt') "MARL界面预览 $version`nBuild: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n" -Encoding UTF8

Get-ChildItem $release -Recurse -File | Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash)  $($_.Path.Substring($release.Length + 1))" } |
    Set-Content (Join-Path $release 'SHA256SUMS.txt') -Encoding ASCII

$zipPath = Join-Path $root "release\MARL界面预览_v$version.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $release -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "Release: $release"
Write-Host "Zip:     $zipPath"
Write-Host "SHA256:  $((Get-FileHash $zipPath -Algorithm SHA256).Hash)"
