from datetime import datetime
import json
from pathlib import Path
import shutil

vault = Path('D:/obsidianNOTE/ammo')
work = Path('D:/Desktop/MARL项目/.work/behavior_visual_refine_20261028')
targets = ['10_项目/MARL/实操_任务规划中间层规划能力版v2.md',
           '10_项目/MARL/00_项目入口.md']
backup = work / ('obsidian_before_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
backup.mkdir()
mapping = {}
for relative in targets:
    source = vault / relative
    destination = backup / source.name
    shutil.copy2(source, destination)
    mapping[str(source)] = str(destination)
(backup / 'mapping.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')

section = '''

### 2026-10-28 工作台内的任务角色、侦察覆盖与避障证据

**用户决定**：最终展示以工作台为主，参考独立串行回放的表达，在工作台代码内实现。参考的串行记录与并行调度运行不是同一数据，不把参考动画移入后冒充当前执行结果。

**已实现**：工作台原任务大画面继续复用同一画布。坚守任务用固定成员色、实际交接岗位与待命位、当前主班/接班角色卡、可点击的交接时间带解释过程；两成员任务不画未使用的第二岗位。角色直接取本次运行快照，完成后保留真实末帧，不补画撤离。侦察任务按已记录测绘点逐步显示传感覆盖及当前目标。任务窗口可单独开关碰撞盒、当前规划路径和受阻直线对照；侧栏提供路径长度、规划净空及已经记录的绕行跳转。道路底图仍不绘制。

**代码与时间依据**：`mock_fleet.py` 在行为步后追加审计用 `behavior_detail`，保存角色/参数/增量路径，接近路线另记 `approach_route`；不送入 coordinator 的执行反馈校验。`run_demo_v2.py` 保存绝对记录时刻，前端按事件 `sim_s` 重建状态，不能直接把路径局部 `t` 当全局时间。旧日志缺少路径时明确提示；新建带行为与绕障的运行会自动记录，工作台默认优先选择有细节日志的运行。

**已验证结果**：新运行 `planning_middle_demo/outputs/workbench_20261028_174224_708566/`，6/6完成，187仿真秒。与 `workbench_behavior_20261028` 相比，原报告字段全部一致，953条规划/反馈/状态审计逐条一致（含904条采纳反馈）；仅新增诊断审计及 `behavior_details` 标记。原参考JSON、旧工作台轨迹、`behaviors.py`、`behavior_runtime.py`、`city_nav.py` 的起始哈希全部保持。85项Python测试通过；无头Edge核对六任务共318个执行时刻、交接角色、标签不重叠、只显示本任务成员、不提前展示路径、节点/绕行跳转、旧日志与Esc返回，无页面脚本错误。1366×900窗口下画布1005×约397。

主入口仍为 `http://127.0.0.1:8766`，选择J5看交接、J3看逐步覆盖；J4的116秒记录含受阻绕行，可在路径侧栏回看。原始数据、独立参考与其同期修改保留，最终主展示不依赖打开参考页。证据在 `.work/behavior_visual_refine_20261028/final-qa.json`、`final-data-proof.json`；截图为 `outputs/工作台展示_20261028/workbench-hold-roles.png`、`workbench-recon-coverage.png`、`workbench-path-evidence.png`。

**解释边界**：路径净空是已记录规划路径的几何指标，未作为现实无碰撞保证；本轮未训练、未连接ROS/Gazebo，也未修改任务规划与行为决策。笔记写前快照在本轮 `.work` 的 `obsidian_before_<时间>/`，仅恢复对应文件或段落并先保留新改动；未提交笔记。
'''
p = vault / targets[0]
content = p.read_text(encoding='utf-8')
assert '### 2026-10-28 工作台内的任务角色、侦察覆盖与避障证据' not in content
p.write_text(content.rstrip() + section + '\n', encoding='utf-8')
p = vault / targets[1]
content = p.read_text(encoding='utf-8')
anchor = '## 本地文件入口与目录维护\n'
addition = '\n2026-10-28主展示统一到工作台任务大画面：已接入交接角色/时间带、逐步侦察覆盖及实际路径诊断；新运行6/6完成且原953条规划/反馈/状态记录逐条一致。85项测试和318个执行时刻检查通过。见 [[实操_任务规划中间层规划能力版v2#2026-10-28 工作台内的任务角色、侦察覆盖与避障证据]]。独立串行回放保留作参考，与工作台并行执行分开解释。\n'
assert anchor in content
p.write_text(content.replace(anchor, anchor + addition, 1), encoding='utf-8')
for relative in targets:
    saved = (vault / relative).read_text(encoding='utf-8')
    assert '953条' in saved and '318个' in saved
    print('已写入并回读：' + relative)
print('写前备份：' + str(backup))
print((vault / targets[0]).read_text(encoding='utf-8')[-560:])
