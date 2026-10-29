$ErrorActionPreference = 'Stop'
$vaultRoot = 'D:\obsidianNOTE\ammo'
$topicRoot = Join-Path $vaultRoot '10_项目\MARL'
$workRoot = 'C:\Users\ammo\Desktop\MARL项目\.work\platform_review_20261026'
$payload = Get-Content -LiteralPath (Join-Path $workRoot 'notes_payload.json') -Raw | ConvertFrom-Json
$archiveRoot = Join-Path $topicRoot '历史\20261026_新材料前'
if (Test-Path -LiteralPath $archiveRoot) { throw 'Archive destination already exists; inspect before proceeding.' }
$backupBase = 'C:\Users\ammo\Desktop\MARL项目\.work\backups'
$backupRoot = Join-Path $backupBase ('2026-10-26_platform_review_' + [Guid]::NewGuid().ToString('N').Substring(0,8))
$utf8 = [Text.UTF8Encoding]::new($false)
# All paths are explicit scoped note paths; no recursive delete or move is used.
foreach ($entry in $payload.files) {
    if ([IO.Path]::GetFileName($entry.name) -ne $entry.name) { throw 'Unexpected note path.' }
    $target = Join-Path $topicRoot $entry.name
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry.expected_sha256) {
        throw ('Concurrent note change detected: ' + $entry.name)
    }
}
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$backupNotes = Join-Path $backupRoot 'notes'
New-Item -ItemType Directory -Path $backupNotes | Out-Null
$manifest = @()
foreach ($entry in $payload.files) {
    $target = Join-Path $topicRoot $entry.name
    $backupPath = Join-Path $backupNotes $entry.name
    Copy-Item -LiteralPath $target -Destination $backupPath
    $backupHash = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash
    if ($backupHash -ne $entry.expected_sha256) { throw ('Backup mismatch: ' + $entry.name) }
    $manifest += [pscustomobject]@{
        original=$target
        backup=$backupPath
        archive=(Join-Path $archiveRoot ('旧版_' + $entry.name))
        before_sha256=$backupHash
        before_bytes=(Get-Item -LiteralPath $target).Length
    }
}
$sourceRoot = Join-Path $backupRoot 'sources'
New-Item -ItemType Directory -Path $sourceRoot | Out-Null
$sources = @()
foreach ($sourceName in @('智能体开发训练平台技术实施方案.docx','外协内容.docx')) {
    $source = Join-Path 'C:\Users\ammo\Desktop' $sourceName
    $copyPath = Join-Path $sourceRoot $sourceName
    Copy-Item -LiteralPath $source -Destination $copyPath
    $sourceHash = (Get-FileHash -LiteralPath $source).Hash
    if ((Get-FileHash -LiteralPath $copyPath).Hash -ne $sourceHash) { throw 'Source backup mismatch.' }
    $sources += [pscustomobject]@{source=$source;copy=$copyPath;sha256=$sourceHash}
}
$manifestData = [pscustomobject]@{date='2026-10-26';scope='Six MARL core notes only; source documents and business code unchanged';notes=$manifest;sources=$sources}
[IO.File]::WriteAllText((Join-Path $backupRoot 'manifest.json'),($manifestData | ConvertTo-Json -Depth 8),$utf8)
# Preserve exact original note bytes inside the vault, then replace current text.
New-Item -ItemType Directory -Path $archiveRoot | Out-Null
foreach ($entry in $payload.files) {
    Copy-Item -LiteralPath (Join-Path $backupNotes $entry.name) -Destination (Join-Path $archiveRoot ('旧版_' + $entry.name))
}
$lines = @(
    '---',
    'type: index',
    "updated: '2026-10-26'",
    'status: 历史快照',
    'cssclasses: [ammo-note]',
    '---',
    '# 新材料前核心笔记历史快照',
    '',
    '> [!warning] 历史用途',
    '> 本目录保存 2026-10-26 本轮整理前的 6 篇笔记原字节内容。它们包含旧假设、旧排期和历史结论，不能直接当作当前方案或新一次验证结果。当前阅读从 [[10_项目/MARL/00_项目入口]] 开始。',
    '',
    '用户本轮明确允许删减旧笔记。处理方式是精简当前正文，保留旧全文及库外备份；未删除实验、代码、附件或其他笔记，未提交 Git，未查询或改动自动化。',
    '',
    '## 原文',
    ''
)
foreach ($entry in $payload.files) { $lines += ('- [[旧版_' + [IO.Path]::GetFileNameWithoutExtension($entry.name) + ']]') }
$lines += @(
    '',
    '## 恢复',
    '',
    ('库外备份：' + [char]96 + $backupRoot.Replace('\','/') + [char]96 + '。'),
    'manifest.json 记录原路径、历史路径及整理前 SHA256；notes/ 为精确副本，sources/ 为两份输入 DOCX 的快照。',
    '恢复时只选相应笔记，并先备份整理后的新内容；不要对整个笔记库执行 reset、clean 或覆盖还原。',
    '',
    '## 当前内容分工',
    '',
    '- 需求与验收：材料来源、模块责任和数字口径。',
    '- 方案：改动量与通用实现建议。',
    '- 工具与工程核对：新材料的技术问题、接口和官方依据。',
    '- 阶段计划：按证据推进，不沿用未确认日期。',
    '- 项目入口：只保留状态和导航；旧优化方案仅保留跳转。',
    ''
)
[IO.File]::WriteAllText((Join-Path $archiveRoot '00_整理说明.md'),($lines -join "`n"),$utf8)
foreach ($entry in $payload.files) {
    $target = Join-Path $topicRoot $entry.name
    # Reread immediately before each mutation; preserve edits from other chats.
    if ((Get-FileHash -LiteralPath $target).Hash -ne $entry.expected_sha256) { throw ('Concurrent edit before write: ' + $entry.name) }
    [IO.File]::WriteAllText($target,$entry.content,$utf8)
}
$report=@()
foreach ($entry in $payload.files) {
    $target=Join-Path $topicRoot $entry.name
    $readback=[IO.File]::ReadAllText($target)
    if ($readback -cne $entry.content) { throw ('Readback mismatch: ' + $entry.name) }
    $archived=Join-Path $archiveRoot ('旧版_' + $entry.name)
    if ((Get-FileHash -LiteralPath $archived).Hash -ne $entry.expected_sha256) { throw 'Archive mismatch.' }
    $before=($manifest | Where-Object {$_.original -eq $target}).before_bytes
    $report += [pscustomobject]@{name=$entry.name;before_bytes=$before;after_bytes=(Get-Item -LiteralPath $target).Length;sha256=(Get-FileHash -LiteralPath $target).Hash;readback='exact'}
}
$result=[pscustomobject]@{backup=$backupRoot;archive=$archiveRoot;notes=$report}
[IO.File]::WriteAllText((Join-Path $workRoot 'receipt.json'),($result | ConvertTo-Json -Depth 6),$utf8)
$result | ConvertTo-Json -Depth 6

