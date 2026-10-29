from pathlib import Path
import json, shutil
root=Path('D:/Desktop/MARL项目')
vault=Path('D:/obsidianNOTE/ammo')
backup=root/'.work/obsidian_backups/workbench_20261028'
backup.mkdir(parents=True,exist_ok=False)
targets=['10_项目/MARL/实操_任务规划中间层规划能力版v2.md','10_项目/MARL/00_项目入口.md']
for name in targets:
    shutil.copy2(vault/name,backup/Path(name).name)
(backup/'manifest.json').write_text(json.dumps({'paths':targets,'reason':'保留写入前已有未提交及未跟踪笔记'},ensure_ascii=False,indent=2),encoding='utf-8')
# Reread immediately before this incremental edit, preserving existing content.
note=vault/targets[0]
content=note.read_text(encoding='utf-8')
section='''

## 2026-10-28：本地规划演示工作台

**已实现**：参考 `D:/Desktop/M2/M2/` 的工作台组织方式，自行建设界面，业务读取、运行 `planning_middle_demo` 自有代码与日志。主地图、任务进度、平台状态、规划次数和事件共用反馈时间轴；新建演示复用 `run_demo_v2.simulate()`，每轮保存到新的 `planning_middle_demo/outputs/workbench_<时间>/`。

启动：双击 `D:/Desktop/MARL项目/planning_middle_demo/启动工作台.cmd`，或在项目根目录执行：

```powershell
py -3.14 planning_middle_demo/workbench_server.py --open
```

浏览器访问 `http://127.0.0.1:8766`；仅监听本机、只用 Python 标准库与本地前端。源码为 `workbench_server.py`、`workbench/index.html`、`workbench/styles.css`、`workbench/app.js`。相同服务已运行时再次启动可复用；其他端口占用可使用 `--port 8767`。

**原有输出已接入**：“原始可视化”直接打开所选运行的 `trajectory.html`、`report.html`，保留原播放器的底图/地标/轨迹/编号/筛选等操作；原播放器使用自己的回放时钟。另接入已保存的 `behavior_demo` 与固定时间轴示意，标注为独立已有产物，不作为本轮运行结果。

**本轮实测**（Windows Python 3.14.7、无头 Edge）：83项Python测试通过，浏览器逐秒核对六组运行的314个时刻，完成数与规划次数均与日志一致；播放/暂停/拖动/选择/图层/源文件查看/原始回放切换/390px窄屏检查通过，无脚本错误。

| 配置 | 实际结果 | 证据目录（相对 `planning_middle_demo/outputs/`） |
| --- | --- | --- |
| 基础场景正常、瞬移 | 6/6，t=50 | `workbench_20261028_122050_750769` |
| 基础场景失败、瞬移；通过网页表单发起 | 6/6，1次重试，t=50 | `workbench_20261028_121742_502947` |
| 基础场景超时、瞬移 | 6/6，1次超时及重试，t=46 | `workbench_20261028_122051_592147` |
| 基础场景失联、瞬移 | 5/6，未结算，t=59 | `workbench_20261028_122052_426684` |
| 基础场景偏差、瞬移 | 6/6，2次偏差触发，t=47 | `workbench_20261028_122053_240767` |
| 城市场景、逐步运动及静态绕障 | 6/6，t=56；11段道路，场景范围内7个碰撞盒 | `workbench_20261028_122054_087703` |

验证明细及原 `avoid_run` 文件哈希对照：`.work/workbench_qa/integration.json`；浏览器检查：`browser.cjs`、`final.cjs`、`final-browser.json`；截图：`outputs/工作台展示_20261028/`。原 `avoid_run` 文件在本轮集成验证前后哈希一致。新运行保留 `request.json`、`worker.log` 以及原格式报告、场景、清单、日志和播放器。

边界：这是本地模拟结果工作台，暂停只暂停回放；未因此接通ROS/Gazebo，也未修改规划器、协调器或执行器算法。原模型工作量达标、独立行为演示、固定时间轴示意分别说明，不混称任务行为验收。下一步可直接在网页演示五种预设模式；真实模块联调仍需按已有审查清单另行验证。
'''
assert '## 2026-10-28：本地规划演示工作台' not in content
note.write_text(content.rstrip()+section+'\n',encoding='utf-8')
index=vault/targets[1]
content=index.read_text(encoding='utf-8')
anchor='## 已有成果与限制\n'
addition='''
- **2026-10-28 规划演示工作台**：[[实操_任务规划中间层规划能力版v2#2026-10-28：本地规划演示工作台]]。双击 `D:/Desktop/MARL项目/planning_middle_demo/启动工作台.cmd` 后访问 `http://127.0.0.1:8766`；地图/任务/事件同步回放，新建演示调用自有规划器，已接入原 `trajectory.html`、报告、已有行为演示及固定时间轴示意。83项测试与314个回放时刻核对通过；仍为本地模拟，未改变真实联调状态。
'''
assert anchor in content
index.write_text(content.replace(anchor,anchor+addition,1),encoding='utf-8')
for name in targets:
    saved=(vault/name).read_text(encoding='utf-8')
    assert '314' in saved and '启动工作台.cmd' in saved
    print('已写入并回读：'+name)
print('恢复副本：'+str(backup))
