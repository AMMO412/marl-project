$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$out = Join-Path $root 'dist'
New-Item -ItemType Directory -Force $out | Out-Null
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$sources = Get-ChildItem (Join-Path $root 'src') -Filter '*.cs' | ForEach-Object { $_.FullName }
$cscArgs = @(
  '/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/codepage:65001',
  "/out:$out\MARL界面预览.exe",
  '/r:System.dll', '/r:System.Core.dll', '/r:System.Drawing.dll',
  '/r:System.Windows.Forms.dll', '/r:System.Web.Extensions.dll',
  "/r:$(Join-Path $root 'lib\webview2\Microsoft.Web.WebView2.Core.dll')",
  "/r:$(Join-Path $root 'lib\webview2\Microsoft.Web.WebView2.WinForms.dll')"
) + $sources
& $csc $cscArgs
if ($LASTEXITCODE -ne 0) { throw "C# build failed with exit code $LASTEXITCODE" }
Copy-Item (Join-Path $root 'lib\webview2\Microsoft.Web.WebView2.Core.dll') $out -Force
Copy-Item (Join-Path $root 'lib\webview2\Microsoft.Web.WebView2.WinForms.dll') $out -Force
Copy-Item (Join-Path $root 'lib\webview2\WebView2Loader.dll') $out -Force
Copy-Item (Join-Path $root 'lib\webview2\LICENSE.txt') (Join-Path $out 'WebView2-LICENSE.txt') -Force
Copy-Item (Join-Path $root 'lib\webview2\NOTICE.txt') (Join-Path $out 'WebView2-NOTICE.txt') -Force
Write-Host "Built: $out\MARL界面预览.exe"
