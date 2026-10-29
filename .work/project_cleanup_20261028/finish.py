"""Update directory navigation and verify retained artifacts after the file moves."""
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path('C:/Users/ammo/Desktop/MARL项目')
VAULT = Path('D:/obsidianNOTE/ammo')
WORK = ROOT / '.work/project_cleanup_20261028'
if (WORK / 'finish_receipt.json').exists():
    raise SystemExit('Already completed; original backups must not be overwritten.')
manifest = json.loads((WORK / 'manifest.json').read_text(encoding='utf-8-sig'))
backup = Path(manifest['backup']).parent

note_names = [
    '10_项目/MARL/00_项目入口.md',
    '10_项目/MARL/调研_四类平台公开参数与Gazebo衔接.md',
    '10_项目/MARL/学习_ROS与Gazebo入门.md',
    '10_项目/MARL/历史/暂时用不到/对照_文档逐项指标与MARLlib实现边界.md',
]
status = subprocess.run(['git', '-C', str(VAULT), 'status', '--short', '--', *note_names],
                        capture_output=True, check=True, encoding='utf-8').stdout
(backup / 'vault_status_before.txt').write_text(status, encoding='utf-8')
note_mapping = []
for name in note_names:
    source = VAULT / name
    # Back up exact current bytes, including previously uncommitted/untracked work.
    destination = backup / 'obsidian_before' / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    assert source.read_bytes() == destination.read_bytes()
    note_mapping.append({'source': str(source), 'backup': str(destination)})
(backup / 'obsidian_mapping.json').write_text(json.dumps(note_mapping, ensure_ascii=False, indent=2), encoding='utf-8')

note_edits = {}
for name in note_names:
    path = VAULT / name
    text = path.read_text(encoding='utf-8')
    if name.endswith('00_项目入口.md'):
        section = '''## 本地文件入口与目录维护

2026-10-28按用户要求整理项目文件：[本地学习入口](<C:/Users/ammo/Desktop/MARL项目/学习入口.md>)。参考文档归入 `资料/需求与任务`、`资料/平台调研`、`资料/接口说明`、`资料/汇报材料`；原 `output/` 合并到 `outputs/`。代码及各工程运行结果保持原位，清理了缓存、确认相同的重复备份和GIF中间帧；成品与原始反馈轨迹保留。固定时间轴动态示意从临时目录移到 `outputs/任务动态示意_20261027/index.html`，区别于物理执行回放。

整理依据、恢复备份及逐项路径映射见 [项目整理记录](<C:/Users/ammo/Desktop/MARL项目/outputs/目录整理_20261028.md>)。本次仅整理目录与链接，没有重新验证算法或系统功能。

'''
        assert '## 本地文件入口与目录维护' not in text
        text = text.replace('## 当前阅读顺序\n', section + '## 当前阅读顺序\n', 1)
    elif '调研_四类平台' in name:
        for filename in ['四类平台参数与对接说明_会议展示版.docx',
                         '四类平台参数指标与Gazebo实现详尽调研_更新版20261027.docx']:
            old = 'C:/Users/ammo/Desktop/MARL项目/' + filename
            assert old in text
            text = text.replace(old, 'C:/Users/ammo/Desktop/MARL项目/资料/平台调研/' + filename)
        text = text.replace("updated: '2026-10-27'", "updated: '2026-10-28'", 1)
    elif '学习_ROS' in name:
        old = 'C:/Users/ammo/Desktop/MARL项目/四类平台参数指标与Gazebo实现详尽调研.docx'
        assert old in text
        text = text.replace(old, 'C:/Users/ammo/Desktop/MARL项目/outputs/平台参数调研/四类平台参数指标与Gazebo实现详尽调研.docx')
        text = text.replace("updated: '2026-10-26'", "updated: '2026-10-28'", 1)
    else:
        old = 'C:/Users/ammo/Desktop/MARL项目/对手编队决策模型建模询价要求与报价单20261008.md'
        assert old in text
        text = text.replace(old, 'C:/Users/ammo/Desktop/MARL项目/资料/需求与任务/对手编队决策模型建模询价要求与报价单20261008.md')
    assert text != path.read_text(encoding='utf-8')
    path.write_text(text, encoding='utf-8')
    assert path.read_text(encoding='utf-8') == text
    note_edits[name] = '补充本地目录入口与整理记录' if name.endswith('00_项目入口.md') else '修正文档路径；保留原有结论与历史说明'

prompt = ROOT / 'outputs/figures/三类任务_生图提示词.md'
text = prompt.read_text(encoding='utf-8')
assert 'MARL项目/output/figures/' in text
prompt.write_text(text.replace('MARL项目/output/figures/', 'MARL项目/outputs/figures/'), encoding='utf-8')
pipeline = ROOT / 'outputs/20261026-对比询价指标/pipeline-state.yaml'
text = pipeline.read_text(encoding='utf-8')
assert 'MARL项目/output/' in text
pipeline.write_text(text.replace('MARL项目/output/', 'MARL项目/outputs/'), encoding='utf-8')

# Normalize local image destinations left escaped by the document converter.
image_checks = []
for document in (ROOT / '资料').rglob('*.md'):
    text = document.read_text(encoding='utf-8')
    def normalize(match):
        target = match.group(2)
        if re.match(r'https?://', target):
            return match.group(0)
        target = target.replace('\\_', '_')
        resolved = document.parent / target
        assert resolved.is_file(), (document, target)
        image_checks.append(str(resolved.relative_to(ROOT)))
        return match.group(1) + target + match.group(3)
    updated = re.sub(r'(!\[[^\n]*?\]\()([^)\n]+)(\))', normalize, text)
    if updated != text:
        document.write_text(updated, encoding='utf-8')

with zipfile.ZipFile(manifest['backup']) as archive:
    assert archive.testzip() is None

report = f'''# 项目目录整理记录 · 2026-10-28

## 已完成

- 将根目录参考文档、转换记录与图片附件归入 `资料/` 的需求与任务、平台调研、接口说明、汇报材料四类。不同用途的版本均保留。
- 将 `output/figures/` 与旧流程状态目录合并进 `outputs/`，移除空的旧目录。
- 将 `.work/task_schematics_20261027/standalone.html` 移到 `outputs/任务动态示意_20261027/index.html`。这是自包含固定时间轴示意页；验证脚本、截图和记录仍在原工作目录。
- 新增项目入口、资料索引与成果索引，修正资料图片及相关 Obsidian 文档链接。
- 代码、场景、任务、原始实验记录和各工程运行结果保持原位；导航服务仍使用原目录。WSL MARLlib 未改动。

## 删除依据

共删除 **{manifest['deleted_files']} 个文件，约 {manifest['deleted_bytes']/1024/1024:.2f} MB**：

| 内容 | 依据与保留内容 |
| --- | --- |
| 四处 `__pycache__/` | Python 自动生成的字节码，可重新生成 |
| `_extract/` | 文档临时提取文本；正式文档与报告保留 |
| `.slidep/` | 旧工具命令与日志；PPT 保留 |
| 两份重复 Word 备份 | 已核对 SHA256 相同，分别保留另一份相同内容的副本 |
| `showcase_gazebo_20261028/gif_frames/` 的111张中间帧 | 成品 GIF、轨迹、回放 HTML、生成截图与编码脚本保留；成品尺寸与记录一致，轨迹哈希与成品元数据一致 |

`.work/` 和 `.workbuddy/` 仍有唯一的生成脚本、历史记录与恢复备份，因此保留。旧版本代码、不同用途的报告和素材 ZIP 没有按名称或年代删除。

## 核对结果与范围

搬迁后核对了358个保留文件的 SHA256；后续有意修改的内容仅为入口、文字路径与 Markdown 图片链接。资料中的6张图片均能按新位置找到。没有运行训练或重新宣称历史测试结果。

导航服务正在运行，其 `robot_navigation_lab/outputs/live_*` 与 `console_*` 日志保留原位，也不纳入静态备份与哈希核对，避免读取正在独占写入的日志。旧流程目录 `20261026-对比询价指标/` 当前只有 `pipeline-state.yaml`；其中列出的阶段产物在整理前已不在本目录，本次未补造结果。历史一次性生成脚本中的旧路径按原记录保留，再次运行前应参考映射调整。

## 恢复与明细

- 项目外恢复备份：[project_before_cleanup.zip](<{Path(manifest['backup']).as_posix()}>)，已完成 ZIP CRC 校验。
- 备份包含整理前的静态文件与被删除文件；排除项见上文。整理开始后的文件修改不会自动进入此备份。
- 每项搬迁、删除理由和整理前哈希：[manifest.json](../.work/project_cleanup_20261028/manifest.json)。项目外备份目录也保存了同一份清单。
- 修改前 Obsidian 的精确副本、路径映射与 Git 状态保存在同一项目外备份目录的 `obsidian_before/`、`obsidian_mapping.json`、`vault_status_before.txt`。笔记修改未提交 Git，未改已有暂存区。
- 恢复时先保留之后的新改动，再从 ZIP 中只提取需要的文件；旧路径到新路径的对应关系见清单，避免整体覆盖当前工作。

[项目入口](../学习入口.md) · [资料索引](../资料/README.md) · [成果索引](README.md)
'''
(ROOT / 'outputs/目录整理_20261028.md').write_text(report, encoding='utf-8')
assert (ROOT / 'outputs/目录整理_20261028.md').read_text(encoding='utf-8') == report

result = {'backup': manifest['backup'], 'note_updates': note_edits, 'image_links_verified': len(image_checks), 'zip_crc_verified': True}
(WORK / 'finish_receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
