from pathlib import Path
import hashlib
import json
import shutil

root = Path('D:/Desktop/MARL项目')
evidence = root / '.work/workbench_task_theater_20261028'
source = root / 'planning_middle_demo/outputs/workbench_behavior_20261028'
before = json.loads((evidence / 'source_hashes.json').read_text())
after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}
assert before == after
result = json.loads((evidence / 'browser-result.json').read_text())
result['sourceArtifactsUnchanged'] = True
(evidence / 'browser-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

readme = root / 'planning_middle_demo/README_v2.md'
text = readme.read_text(encoding='utf-8')
start = text.index('1. **演示总览（唯一回放入口）**')
end = text.index('3. **新建演示**', start)
text = text[:start] + '''1. **按任务观看执行**：道路与建筑底图已从工作台展示中移除，原“跟踪平台”改为“选择任务”。选择任务或点击任务卡片，直接打开接近整窗的大画幅执行回放，从该任务的行为启动时刻以1倍速播放。只显示该任务的成员、路线/检查点/岗位或已记录探索点，不混入其他任务。
2. **大画幅任务回放**：顶部可切换任务，选择“从任务下发看起”或“从执行开始”；时间轴仅覆盖所选区间，并显示区间经过时间，绝对仿真时刻在右侧。右侧显示阶段、工作量、行为指标、成员反馈和最近事件。任务结束自动停止，最终动作结构保留；点播放可重播，关闭或Esc返回总览。任务视图复用同一个画布，不新增第二套播放器。窄屏可在窗口内部向下滚动查看细节。
''' + text[end:]
anchor = '## 与 v1 的区别'
addition = '''2026-10-28按任务大画幅版本验证：无头Edge逐项检查六个任务共318个时刻；在1600×1050视口下，画布为1239×约621。检查了从执行开始自动播放、仅显示任务成员、任务区间与相对时钟、完成后重播、切换任务、返回总览、Esc和390px窄屏，无脚本错误；8项工作台相关Python测试通过。原动作目录8个文件哈希未变。证据在 `.work/workbench_task_theater_20261028/`，截图为 `outputs/工作台展示_20261028/task-patrol-large.png`、`task-exploration-large.png`、`task-handover-large.png`。下面早期展示验证记录保留为历史。

'''
text = text.replace(anchor, addition + anchor, 1)
readme.write_text(text, encoding='utf-8')

output = root / 'outputs/工作台展示_20261028/README.md'
text = output.read_text(encoding='utf-8')
first = text.index('\n\n')
text = text[:first] + '''

当前版本为按任务大画幅回放：删除道路/建筑底图，以任务选择替代平台跟踪。选中后直接从执行开始播放，只有本任务成员与动作；右侧提供阶段、指标、成员反馈和事件。支持从任务下发看起、切换任务、重播及返回总览。

- [巡逻任务大画幅](task-patrol-large.png)
- [探索任务大画幅](task-exploration-large.png)
- [接替任务大画幅](task-handover-large.png)

本轮六任务318个时刻和交互检查通过，8项相关Python测试通过，无页面脚本错误；原动作数据未改。详细证据在 `.work/workbench_task_theater_20261028/`。以下保留前几版截图与记录。
''' + text[first:]
output.write_text(text, encoding='utf-8')

vault = Path('D:/obsidianNOTE/ammo')
paths = ['10_项目/MARL/实操_任务规划中间层规划能力版v2.md', '10_项目/MARL/00_项目入口.md']
backup = evidence / 'obsidian_before'
backup.mkdir(exist_ok=False)
for relative in paths:
    shutil.copy2(vault / relative, backup / Path(relative).name)

note = vault / paths[0]
text = note.read_text(encoding='utf-8')
section = '''

### 同日再改：去底图、按任务直接进入大画幅执行

用户反馈前版仍小且杂乱，平台跟踪难以看懂动作。已按要求移除工作台的道路/建筑底图，用“选择任务”替代平台下拉；点击任务直接打开接近整窗的大画幅，从该任务行为启动时刻以1倍速播放，仅绘制该任务成员与已记录动作。增加检查点、岗位/待命位及已记录探索点标注；右侧显示当前阶段、行为指标、工作量、成员状态/坐标及近期事件。

观看区间可在“从任务下发看起”和“从执行开始”之间切换，时间轴只覆盖所选任务区间，主时钟表示区间经过时间，绝对仿真时刻在右侧。任务结束保留最终结构，播放可重播；关闭或Esc返回总览。任务视图移动并复用原画布，退出后还原；未增加重复播放器。窄屏在任务窗口内滚动查看详情。

**验证结果**：8项工作台相关Python测试通过；无头Edge检查六个任务共318个时刻、任务切换、独立区间与时钟、排除其他任务成员、完成后重播、从任务/执行开始、返回总览、Esc和390px窄屏，无页面脚本错误。在1600×1050视口下，六项任务画布均为1239×约621。原动作目录8个文件哈希一致；本轮仅修改前端及说明，读取已有执行记录，未改变规划/执行算法或动作数据。

证据：`.work/workbench_task_theater_20261028/browser-result.json`、`browser.cjs`、`source_hashes.json`；截图：`outputs/工作台展示_20261028/task-patrol-large.png`、`task-exploration-large.png`、`task-handover-large.png`。源文件及笔记写前备份在本轮工作目录的`before/`与`obsidian_before/`。刷新 `http://127.0.0.1:8766` 后在“选择任务”中观看。
'''
assert '### 同日再改：去底图、按任务直接进入大画幅执行' not in text
note.write_text(text.rstrip() + section + '\n', encoding='utf-8')

index = vault / paths[1]
text = index.read_text(encoding='utf-8')
start = text.index('- **2026-10-28 规划演示工作台')
end = text.index('\n', start)
text = text[:start] + '- **2026-10-28 规划演示工作台（按任务大画幅）**：[[实操_任务规划中间层规划能力版v2#同日再改：去底图、按任务直接进入大画幅执行]]。访问 `http://127.0.0.1:8766`，选择任务后从执行开始播放，仅显示本任务成员与动作；道路底图已去除，平台跟踪替换为任务选择。六任务318个时刻与交互验证通过，原始动作数据未改。' + text[end:]
index.write_text(text, encoding='utf-8')
for relative in paths:
    saved = (vault / relative).read_text(encoding='utf-8')
    assert '318' in saved and '大画幅' in saved
    print('Saved and read back:', relative)
print('Source artifacts unchanged:', len(after))
