param([string]$Version='0.6.0-20261111',[string]$OutputDirectory='')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$repo=Split-Path $root -Parent
$cache=Join-Path $root '.cache'
New-Item -ItemType Directory -Force $cache|Out-Null
if(!$OutputDirectory){$OutputDirectory=Join-Path $root "release\MARL协同规划_v$Version"}
$release=[IO.Path]::GetFullPath($OutputDirectory)
if(Test-Path -LiteralPath $release){throw "输出已存在，请指定新目录：$release"}
New-Item -ItemType Directory -Path $release|Out-Null
function Copy-Tree($src,$dst,$exclude) {
 New-Item -ItemType Directory -Force $dst|Out-Null
 Get-ChildItem -LiteralPath $src -Force|Where-Object {$exclude -notcontains $_.Name}|ForEach-Object {
  $target=Join-Path $dst $_.Name
  if($_.PSIsContainer){Copy-Tree $_.FullName $target $exclude}else{Copy-Item -LiteralPath $_.FullName -Destination $target}
 }
}
function Download($name,$url,$minimum) {
 $path=Join-Path $cache $name
 if(!(Test-Path -LiteralPath $path)){Invoke-WebRequest -Uri $url -OutFile $path -UseBasicParsing}
 if((Get-Item -LiteralPath $path).Length -lt $minimum){throw "下载不完整：$name"}
 return $path
}
$pythonZip=Download 'python-3.14.7-embed-amd64.zip' 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip' 12000000
if((Get-FileHash -LiteralPath $pythonZip -Algorithm SHA256).Hash -ne 'D297E5FF019966817AD8502465176139F2D3D840FA4ED84B13BED399A6AB1F15'){throw 'Python 官方 SHA256 不匹配'}
$webview=Download 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe' 'https://go.microsoft.com/fwlink/?linkid=2124701' 100000000
$net=Download 'ndp48-x86-x64-allos-enu.exe' 'https://go.microsoft.com/fwlink/?linkid=2088631' 100000000
foreach($installer in @($webview,$net)) {
 $sig=Get-AuthenticodeSignature -LiteralPath $installer
 if($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Microsoft Corporation'){throw "微软签名检查失败：$installer ($($sig.Status))"}
}
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$sources=Get-ChildItem (Join-Path $root 'src') -Filter '*.cs'|ForEach-Object FullName
$refs=@('/r:System.dll','/r:System.Core.dll','/r:System.Drawing.dll','/r:System.Windows.Forms.dll','/r:System.Web.Extensions.dll',"/r:$root\lib\webview2\Microsoft.Web.WebView2.Core.dll","/r:$root\lib\webview2\Microsoft.Web.WebView2.WinForms.dll")
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 "/out:$release\MARL界面预览.exe" $refs $sources
if($LASTEXITCODE -ne 0){throw '发布包编译失败'}
foreach($name in @('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll')){Copy-Item -LiteralPath (Join-Path $root "lib\webview2\$name") -Destination $release}
$runtime=Join-Path $release 'runtime'
Expand-Archive -LiteralPath $pythonZip -DestinationPath $runtime
@('python314.zip','.','..\app\planning_middle_demo','..\app')|Set-Content -LiteralPath (Join-Path $runtime 'python314._pth') -Encoding ASCII
New-Item -ItemType Directory -Path (Join-Path $release 'prerequisites'),(Join-Path $release 'LICENSES')|Out-Null
Copy-Item -LiteralPath $webview,$net -Destination (Join-Path $release 'prerequisites')
Copy-Item -LiteralPath (Join-Path $runtime 'LICENSE.txt') -Destination (Join-Path $release 'LICENSES\Python-LICENSE.txt')
Copy-Item -LiteralPath (Join-Path $root 'lib\webview2\LICENSE.txt') -Destination (Join-Path $release 'LICENSES\WebView2-SDK-LICENSE.txt')
Copy-Item -LiteralPath (Join-Path $root 'lib\webview2\NOTICE.txt') -Destination (Join-Path $release 'LICENSES\WebView2-SDK-NOTICE.txt')
$app=Join-Path $release 'app'
$exclude=@('outputs','tests','__pycache__','.work','.pytest_cache','.git','.deleted')
Copy-Tree (Join-Path $repo 'planning_middle_demo') (Join-Path $app 'planning_middle_demo') $exclude
Copy-Tree (Join-Path $repo 'configs') (Join-Path $app 'configs') $exclude
Copy-Tree (Join-Path $repo 'docs') (Join-Path $app 'docs') $exclude
Copy-Item -LiteralPath (Join-Path $repo 'README.md') -Destination $app
Copy-Tree (Join-Path $repo '资料\接口说明') (Join-Path $app '资料\接口说明') $exclude
Copy-Item -LiteralPath (Join-Path $repo '资料\README.md') -Destination (Join-Path $app '资料')
$dataRuns=Join-Path $release 'data\runs'
New-Item -ItemType Directory -Force $dataRuns|Out-Null
$candidates=@()
foreach($run in (Get-ChildItem (Join-Path $root 'dist\data\runs') -Directory|Where-Object Name -like 'workbench_*')) {
 try {
  $m=Get-Content -LiteralPath (Join-Path $run.FullName 'manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json
  $r=Get-Content -LiteralPath (Join-Path $run.FullName 'report.json') -Raw -Encoding UTF8|ConvertFrom-Json
  if($r.all_succeeded){$candidates+=[pscustomobject]@{directory=$run.FullName;id=$run.Name;scenario=$m.workbench_config.scenario}}
 }catch{Write-Warning "跳过不完整样例：$($run.Name)"}
}
$samples=@()
foreach($scenario in @('interop_containment','interop_hold','interop_patrol','interop_recon')) {
 $sample=$candidates|Where-Object scenario -eq $scenario|Sort-Object id -Descending|Select-Object -First 1
 if(!$sample){throw "缺少成功样例：$scenario"}
 Copy-Tree $sample.directory (Join-Path $dataRuns $sample.id) @('.live_state.json','.live_scene.json','.live_request.json','.live_reply.json','worker.log')
 $samples+=$sample|Select-Object id,scenario
}
$samples|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $release 'SAMPLES.json') -Encoding UTF8
'Portable package: bundled backend, Python and data/runs.'|Set-Content -LiteralPath (Join-Path $release 'PORTABLE.txt') -Encoding ASCII
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'portable-launch.ps1') -Destination (Join-Path $release 'launch.ps1')
@('@echo off','cd /d "%~dp0"','powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"','if errorlevel 1 pause')|Set-Content -LiteralPath (Join-Path $release '启动软件.cmd') -Encoding ASCII
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'portable-readme.txt') -Destination (Join-Path $release '启动说明.txt')
"MARL协同规划 $Version`r`nBuild: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`r`nWindows x64 / Python 3.14.7"|Set-Content -LiteralPath (Join-Path $release 'VERSION.txt') -Encoding UTF8
@($pythonZip,$webview,$net)|ForEach-Object {[pscustomobject]@{file=[IO.Path]::GetFileName($_);sha256=(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash}}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $release 'DEPENDENCIES.json') -Encoding UTF8
Write-Host "Staged: $release"
Write-Host 'Verify in an independent directory before making the final ZIP.'
