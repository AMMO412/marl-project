# 融合规划与执行演示项目

当前主程序是 **融合版**：`planning_middle_demo/interop/` 负责统一输入和规划，复用 `planning_middle_demo/` 的执行协调、反馈与工作台。目录名保留以兼容现有导入、脚本及历史报告。

## 启动

- 双击根目录 `启动工作台.cmd`：唯一推荐启动入口；启动后直接打开“融合版中性任务”的新建演示（规划器固定 `interop`、逐步运动）。场景下拉现有融合版中性任务、区域封控（T-SEC）、融合版机动突击（T-ASL 4.1 样例）与 `asl_city` 历史入口；首页默认展示最新一次融合运行，历史回放仍可在运行下拉中选择。
- 区域封控：场景下拉新增 **区域封控 · T-SEC**（4.1 边界控制样例）。样例从集结待机区出发，规划器给出到各占位点的路径，到位后才开始封控；运行完成后在“演示总览”顶部切到 **区域封控** 页签，查看边界占位、在岗巡视、警告与拦阻过程（与“全局分配”是同一轮运行、同一条时间轴）。参数、判定口径与边界见[区域封控实现说明](docs/区域封控任务_20261031.md)。
- 命令行：在 `planning_middle_demo/` 下执行 `python -m interop.cli --help`。
- 完整接口、命令及边界：[融合层说明](planning_middle_demo/interop/README.md)。
- 按调用链阅读源码：[融合版代码讲解](docs/融合版代码讲解_20261030.md)。

## 目录

| 路径 | 用途 |
| --- | --- |
| `planning_middle_demo/` | 正式主程序：融合层、执行基座、工作台；[程序说明](planning_middle_demo/README.md) |
| `planning_middle_demo/tests/` | 基座测试及 `test_interop*.py` 融合对接测试 |
| `configs/` | 可编辑配置与场景导航，指向程序内唯一配置源 |
| `docs/` | 架构、接口、验证状态与维护说明 |
| `资料/` | 外部需求、接口原文、参考材料及索引 |
| `outputs/` | 跨模块报告、演示及交付产物；程序内 outputs 保留运行记录 |
| `.work/`、`.workbuddy/` | 临时工作与恢复记录，含唯一文件，不整体清空 |
| `AGENTS.md` | AI 协作和版本管理规则 |

## 当前目录精简

2026-10-31已将独立Gazebo大素材、旧资料变体和多余运行结果归档到项目外。主程序保留6组代表记录；新运行默认不纳入Git。详情见[整理清单](outputs/目录精简_20261031.md)。源码、当前SDF与必要地图模型保留。

## 当前限制

融合层覆盖五类任务（T-RCN / T-SEC / T-PTL / T-HLD / T-ASL）；T-ASL 的打击与效果判定仍由基座行为层执行，具体支持范围以融合层说明和源码为准。旧基座特定场景不等于融合层能力。本地替身反馈和回放不能作为真实平台/ROS/Gazebo 联调成功的证明。

区域封控是本地行为状态机 + 4.1 输入的回放：不含火力/毁伤，识别按输入标记，传感器遮挡与误拦未建模；指标只对本轮运行记录负责。

本次只整理入口与目录职责，未验证算法效果或完整运行回归。历史报告保留原位置，其结论仅适用于记录中的版本。

## 更多

[项目结构与维护](docs/项目结构.md) · [配置导航](configs/README.md) · [成果目录](outputs/README.md) · [外部资料](资料/README.md)

## 下载与版本同步

公开仓库：[AMMO412/marl-project](https://github.com/AMMO412/marl-project)。

- 只下载当前文件：[下载 main 分支 ZIP](https://github.com/AMMO412/marl-project/archive/refs/heads/main.zip)，解压后阅读本入口并按“启动”操作。当前版本已移除暂不使用的完整Gazebo素材包。
- 需要保留版本历史：`git clone https://github.com/AMMO412/marl-project.git`。
- 本地修改、检查并提交后，用 `git push` 同步到 GitHub；GitHub不会自动获取尚未提交的本地文件。
- ZIP不含Git历史，也不等于完整运行环境；Windows/WSL、Python、Gazebo等依赖按相关说明配置。当前仓库快照不表示已完成真实平台联调或完整验收。
