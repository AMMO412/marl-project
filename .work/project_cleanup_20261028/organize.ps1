$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath('C:\Users\ammo\Desktop\MARL项目').TrimEnd('\')
if ((Get-Location).Path -ne $projectRoot) { throw 'Unexpected working directory.' }
$receiptRoot = Join-Path $projectRoot '.work\project_cleanup_20261028'
$backupRoot = Join-Path 'C:\Users\ammo\.codex\backups\MARL项目' (Get-Date -Format 'yyyyMMdd_HHmmss')
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

function Resolve-ProjectPath([string]$relative) {
    $resolved = [IO.Path]::GetFullPath((Join-Path $projectRoot $relative))
    if (-not $resolved.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Path outside project: $relative" }
    return $resolved
}

$moves = [Collections.Generic.List[object]]::new()
function Add-Move([string]$source, [string]$destination) {
    $from = Resolve-ProjectPath $source
    $to = Resolve-ProjectPath $destination
    if (-not (Test-Path -LiteralPath $from)) { throw "Missing source: $source" }
    if (Test-Path -LiteralPath $to) { throw "Destination already exists: $destination" }
    $moves.Add([pscustomobject]@{source=$source; destination=$destination})
}
$bundles = @(
    @('对手编队决策模型建模询价要求与报价单20261008', '资料\需求与任务'),
    @('五类作战任务_10月26日修改', '资料\需求与任务'),
    @('四类平台参数与对接说明_会议展示版', '资料\平台调研'),
    @('四类平台参数指标与对接要点_简明展示版', '资料\平台调研'),
    @('四类平台参数指标与Gazebo实现详尽调研_更新版20261027', '资料\平台调研')
)
foreach ($bundle in $bundles) {
    foreach ($extension in @('.docx', '.md', '.conversion_profile.json')) {
        Add-Move ($bundle[0] + $extension) (Join-Path $bundle[1] ($bundle[0] + $extension))
    }
    $assets = $bundle[0] + '_files'
    if (Test-Path -LiteralPath (Join-Path $projectRoot $assets)) { Add-Move $assets (Join-Path $bundle[1] $assets) }
}
Add-Move '机器人移动话题说明.md' '资料\接口说明\机器人移动话题说明.md'
Add-Move '五类任务与四类平台_技术沟通汇报_20261027.pptx' '资料\汇报材料\五类任务与四类平台_技术沟通汇报_20261027.pptx'
Add-Move '多无人平台任务规划与仿真验证系统\多无人平台任务规划与仿真验证系统.pptx' '资料\汇报材料\多无人平台任务规划与仿真验证系统.pptx'
Add-Move 'output\figures' 'outputs\figures'
Add-Move 'output\20261026-对比询价指标' 'outputs\20261026-对比询价指标'
Add-Move '.work\task_schematics_20261027\standalone.html' 'outputs\任务动态示意_20261027\index.html'

$deletions = [Collections.Generic.List[object]]::new()
function Add-Deletion([string]$relative, [string]$reason) {
    $target = Resolve-ProjectPath $relative
    if (-not (Test-Path -LiteralPath $target)) { throw "Missing deletion target: $relative" }
    $deletions.Add([pscustomobject]@{path=$relative; reason=$reason})
}
Add-Deletion '_extract' '文档提取的临时纯文本；原始Word和正式报告保留'
Add-Deletion '.slidep' '旧PPT工具的命令记录与日志；PPT保留'
Get-ChildItem -LiteralPath $projectRoot -Recurse -Force -Directory -Filter '__pycache__' | ForEach-Object {
    Add-Deletion ([IO.Path]::GetRelativePath($projectRoot, $_.FullName)) 'Python自动生成的字节码缓存'
}
foreach ($pair in @(
    @('.workbuddy\backups\五类作战任务_加图前_20261024_182048.docx', '.workbuddy\backups\五类作战任务_加图前_20261024_182151.docx'),
    @('.workbuddy\backups\五类作战任务_修改前_20261024_175341.docx', '.workbuddy\backups\五类作战任务_修改前_20261024_175505.docx')
)) {
    if ((Get-FileHash -LiteralPath (Resolve-ProjectPath $pair[0])).Hash -ne (Get-FileHash -LiteralPath (Resolve-ProjectPath $pair[1])).Hash) { throw 'Backup files are not duplicates.' }
    Add-Deletion $pair[1] ('SHA256与保留副本相同：' + $pair[0])
}
$showcase = Resolve-ProjectPath 'robot_navigation_lab\outputs\showcase_gazebo_20261028'
$overview = Get-Content -LiteralPath (Join-Path $showcase 'overview.json') -Raw | ConvertFrom-Json
if ((Get-Item -LiteralPath (Join-Path $showcase 'overview.gif')).Length -ne $overview.bytes) { throw 'GIF size mismatch.' }
if ((Get-FileHash -LiteralPath (Join-Path $showcase 'trace.jsonl')).Hash.ToLower() -ne $overview.trace_sha256) { throw 'GIF source trace mismatch.' }
Add-Deletion 'robot_navigation_lab\outputs\showcase_gazebo_20261028\gif_frames' '111张GIF中间帧；成品GIF、原始轨迹及截图生成/编码脚本保留'

$inventory = @(Get-ChildItem -LiteralPath $projectRoot -Recurse -Force -File | Where-Object {
    [IO.Path]::GetRelativePath($projectRoot, $_.FullName) -notmatch '^robot_navigation_lab\\outputs\\(live_|console_)'
} | ForEach-Object {
    [pscustomobject]@{path=[IO.Path]::GetRelativePath($projectRoot, $_.FullName); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()}
})
$archive = Join-Path $backupRoot 'project_before_cleanup.zip'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$writer = [IO.Compression.ZipFile]::Open($archive, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($item in $inventory) {
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($writer, (Resolve-ProjectPath $item.path), $item.path.Replace('\','/'), [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $writer.Dispose() }
$zip = [IO.Compression.ZipFile]::OpenRead($archive)
try {
    $fileEntries = @($zip.Entries | Where-Object { $_.Name -ne '' })
    foreach ($item in $inventory) {
        $entry = $zip.GetEntry($item.path.Replace('\','/'))
        if (-not $entry) { $entry = $zip.GetEntry($item.path) }
        if (-not $entry -or $entry.Length -ne $item.bytes) { throw ('Backup verification failed: ' + $item.path) }
    }
} finally { $zip.Dispose() }

$deletedFiles = @($inventory | Where-Object {
    $filePath = $_.path
    @($deletions | Where-Object { $filePath -eq $_.path -or $filePath.StartsWith($_.path + '\', [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
})
$plan = [pscustomobject]@{
    date='2026-10-28'; project=$projectRoot; backup=$archive; backup_exclusions='robot_navigation_lab/outputs/live_* and console_* (running service; preserved in place)'; moves=@($moves.ToArray()); deletions=@($deletions.ToArray());
    deleted_files=$deletedFiles.Count; deleted_bytes=($deletedFiles | Measure-Object bytes -Sum).Sum; before=$inventory
}
$plan | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $receiptRoot 'manifest.json') -Encoding utf8
Copy-Item -LiteralPath (Join-Path $receiptRoot 'manifest.json') -Destination (Join-Path $backupRoot 'manifest.json')

foreach ($move in $moves) {
    $source = Resolve-ProjectPath $move.source
    $destination = Resolve-ProjectPath $move.destination
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Move-Item -LiteralPath $source -Destination $destination
}
foreach ($deletion in $deletions) {
    $target = Resolve-ProjectPath $deletion.path
    Remove-Item -LiteralPath $target -Recurse -Force
}
foreach ($empty in @('output', '多无人平台任务规划与仿真验证系统')) {
    $target = Resolve-ProjectPath $empty
    if (@(Get-ChildItem -LiteralPath $target -Force).Count -ne 0) { throw "Directory not empty: $empty" }
    Remove-Item -LiteralPath $target
}

$verified = 0
foreach ($item in $inventory) {
    if ($item.path -in $deletedFiles.path) { continue }
    $newPath = $item.path
    foreach ($move in $moves) {
        if ($item.path -eq $move.source) { $newPath = $move.destination; break }
        if ($item.path.StartsWith($move.source + '\', [StringComparison]::OrdinalIgnoreCase)) {
            $newPath = $move.destination + $item.path.Substring($move.source.Length); break
        }
    }
    $path = Resolve-ProjectPath $newPath
    if (-not (Test-Path -LiteralPath $path)) { throw "Preserved file missing: $newPath" }
    # The running navigation service may still append to live logs; static files must match exactly.
    if ($newPath -match '^robot_navigation_lab\\outputs\\(live_|console_)') { continue }
    if ((Get-FileHash -LiteralPath $path).Hash.ToLower() -ne $item.sha256) { throw "Preserved file changed: $newPath" }
    $verified++
}
[pscustomobject]@{backup=$archive; moved_entries=$moves.Count; deleted_files=$plan.deleted_files; freed_mb=[math]::Round($plan.deleted_bytes/1MB,2); preserved_hashes_verified=$verified} | ConvertTo-Json
