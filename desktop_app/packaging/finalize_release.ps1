param([Parameter(Mandatory=$true)][string]$ReleaseDirectory,[string]$ZipPath='')
$ErrorActionPreference='Stop'
$release=(Resolve-Path -LiteralPath $ReleaseDirectory).Path
if(!(Test-Path -LiteralPath (Join-Path $release 'PORTABLE.txt'))){throw '不是已构建的便携包目录'}
if(!$ZipPath){$ZipPath=$release+'.zip'}
$zipPath=[IO.Path]::GetFullPath($ZipPath)
if(Test-Path -LiteralPath $zipPath){throw '压缩包已存在，请使用新的版本目录，避免覆盖已交付版本。'}
$files=Get-ChildItem -LiteralPath $release -Recurse -File | Where-Object Name -ne 'SHA256SUMS.txt' | Sort-Object FullName
$lines=$files|ForEach-Object {"$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)  $($_.FullName.Substring($release.Length+1))"}
[IO.File]::WriteAllLines((Join-Path $release 'SHA256SUMS.txt'),[string[]]$lines,[Text.UTF8Encoding]::new($false))
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($release,$zipPath,[IO.Compression.CompressionLevel]::Optimal,$true)
$digest=(Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
[IO.File]::WriteAllText($zipPath+'.sha256',"$digest  $([IO.Path]::GetFileName($zipPath))`r`n",[Text.UTF8Encoding]::new($false))
Write-Host "Zip: $zipPath"
Write-Host "Bytes: $((Get-Item -LiteralPath $zipPath).Length)"
Write-Host "SHA256: $digest"
