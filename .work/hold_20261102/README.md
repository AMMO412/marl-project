# T-HLD 验证留痕 · 2026-11-02

本目录是本轮要点坚守（T-HLD）实现的工作留痕，不是产品代码。

| 文件 | 用途 |
| --- | --- |
| `e2e.cjs` | 工作台端到端：新建「要点坚守演示（T-HLD）」→ 断言页签/KPI/在位甘特/画布/计划产物 → 切页签验证时间同步 → 截图 |
| `verify.cjs` | 只读校验：载入既有 T-HLD 运行（`?source=<run_id>`），确认页签、画布高度、甘特与无 console 错误 |
| `smoke_hold.py` | `KeepBehavior` 手工冒烟：用"瞬移到位"把决策与运动解耦，观察事件序列与判定项 |
| `hold_map_card_120s.png` | 工作台 T+120 s：要点/阵位/威胁扇区/在位甘特/时间线 |
| `hold_map_card_all.png` | "全程 · 集结→撤离"镜头 |
| `hold_task_view_120s.png` | 整页（6 项 KPI + 右侧面板） |
| `hold_map_overlay.png` | "全局分配"页签的要点覆盖层 |
| `hold_css_check.png` / `hold_css_overlay.png` | 样式改动后的复检截图 |

运行方式（需先启动工作台服务，脚本默认 `http://127.0.0.1:8899`）：

```powershell
# 在项目根目录
node .work/hold_20261102/verify.cjs workbench_20261102_163225_793094
```

说明：Playwright 用本机 Edge（`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`），
依赖位于 `C:/Users/ammo/.codex/tmp/beijing-map-20261017-01a148de/node_modules/playwright`。
截图里的数字都来自该次运行的记录（`replay.hold`），不是脚本重算的。
