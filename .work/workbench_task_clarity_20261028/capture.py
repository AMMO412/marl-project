from datetime import datetime
import json
from pathlib import Path
import shutil

vault = Path('D:/obsidianNOTE/ammo')
work = Path('D:/Desktop/MARL项目/.work/workbench_task_clarity_20261028')
targets = ['10_项目/MARL/实操_任务规划中间层规划能力版v2.md',
           '10_项目/MARL/00_项目入口.md']
backup = work / ('obsidian_before_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
backup.mkdir()
mapping = {}
for relative in targets:
    source = vault / relative
    shutil.copy2(source, backup / source.name)
    mapping[str(source)] = str(backup / source.name)
(backup / 'mapping.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')

section = '''

### 2026-10-28 突击与坚守改用过程详解，专项记录接入工作台

**纠正与根因**：用户反馈前版仍看不懂，尤其J4。核对后发现 `workbench_20261028_174224_708566` 的J4结构中，四个集结位、四个执行位均为 `[30.26,27.06]`，并非仅标签重叠；而用户指定的专项记录具有分开的目标位置。前版“已接入细节日志”不等于任务展示已经清楚，也不能据此认定动作有效展开。

**本轮实现**：在同一工作台增加“动作详解 / 空间与避障”。J4按机动集结、全员到位、执行动作、结果确认分阶段，每位成员独立轨道，区分已到位等待协同与仍在前往目标，卡片可点击跳转。J5主画面直接显示主班与接班侧、只填已播放部分的角色时间带；原坐标另在空间视图核对。空间镜头按当前阶段固定取景，目标标明成员，避免远距离接近过程压小局部动作；坚守去除未使用待命位对镜头的影响。两种视图复用同一画布与时钟，窄屏过程图可横向查看。

**明确来源**：`workbench_recording.py` 只读适配 `outputs/behavior_20261028_verify/behavior_trace.json`。任务窗口可以切换整套专项串行记录与当前并行记录，来源与成员随数据切换，不拼接轨迹。适配器保留坐标、事件、路径，只转换路径局部时间；片段边界明确记为 `recording_start/end`，不伪造 `plan_emitted`、`job_dispatched` 或 `feedback_applied`。原记录没有的规划/能耗指标显示未记录或未知。代码不是靠打开独立页面实现；独立页面与原JSON未被本轮改写。

**已验证**：88项Python测试通过；专项2388个采样、5190个成员位姿、165条原事件、99条原路径核对通过。浏览器检查两份记录、六任务与两种视图共904个时刻，包含角色/成员隔离、阶段卡点击、数据源切换、单时钟、阶段镜头稳定、标签不重叠、返回总览，未见页面脚本错误。1366和390宽视口检查通过，小屏过程图使用横向滚动。原专项JSON、旧工作台轨迹、行为与导航源码哈希保持。

**使用**：主入口 `http://127.0.0.1:8766`；直接看专项J4：`http://127.0.0.1:8766/?source=behavior_20261028_verify&task=J4&view=spatial&t=354`。工作台内切换任务到J5即可查看坚守；切“动作详解”看阶段与角色。源代码为 `workbench/task_details.js`、`workbench/app.js`、`workbench_recording.py` 和 `workbench_server.py`。证据在 `.work/workbench_task_clarity_20261028/verification.json`、`source-proof.json`，截图在 `outputs/工作台展示_20261028/task-*-v2.png`。

**未声称的结果**：本轮修复展示和数据接入，没有改任务执行算法、重训或重跑；原并行记录的点位重合仍保留并提示。过程图中横向位置表示阶段，不当作新的物理运动。写前笔记备份位于本轮 `.work/workbench_task_clarity_20261028/obsidian_before_<时间>/`，按 `mapping.json` 恢复对应文件前应先保留后续改动；未提交笔记。
'''
p = vault / targets[0]
current = p.read_text(encoding='utf-8')
assert '### 2026-10-28 突击与坚守改用过程详解，专项记录接入工作台' not in current
p.write_text(current.rstrip() + section + '\n', encoding='utf-8')
p = vault / targets[1]
current = p.read_text(encoding='utf-8')
anchor = '## 本地文件入口与目录维护\n'
addition = '\n2026-10-28再次修正任务展示：发现原并行J4的集结位/执行位实际重合；已把指定的专项串行JSON作为明确来源接入工作台，并增加突击分阶段成员轨道、坚守角色时间带及按阶段近景。原执行算法和记录不改写；88项测试、904个任务视图时刻检查通过。见 [[实操_任务规划中间层规划能力版v2#2026-10-28 突击与坚守改用过程详解，专项记录接入工作台]]。\n'
assert anchor in current
p.write_text(current.replace(anchor, anchor + addition, 1), encoding='utf-8')
for relative in targets:
    saved = (vault / relative).read_text(encoding='utf-8')
    assert '904个' in saved and '88项' in saved
    print('已写入并回读：' + relative)
print('恢复备份：' + str(backup))
print((vault / targets[0]).read_text(encoding='utf-8')[-340:])
