# -*- coding: utf-8 -*-
"""出发点改为编成表固定出生位后，更新文档里的时间/距离/指标。"""
import io

DOC_SEC = 'docs/区域封控任务_20261031.md'
DOC_HLD = 'docs/要点坚守任务_20261102.md'
README_INTEROP = 'planning_middle_demo/interop/README.md'
OUT_SEC = 'outputs/区域封控_20261031/README.md'
OUT_HLD = 'outputs/要点坚守_20261102/README.md'


def patch(path, pairs):
    text = io.open(path, encoding='utf-8', newline='').read()
    if '\r\n' in text:
        pairs = [(a.replace('\n', '\r\n'), b.replace('\n', '\r\n'))
                 for a, b in pairs]
    for old, new in pairs:
        if old not in text:
            raise SystemExit('not found in %s: %s' % (path, old[:70]))
        text = text.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='').write(text)
    print('patched', path)


patch(DOC_SEC, [
    ('| T+0 | 6 台平台（5 台地面 + 1 架无人机）在集结待机区待机（`assembly_point`，街区南侧约 55 m） | 编成表 `formation.units[].position` |',
     '| T+0 | 6 台平台（5 台地面 + 1 架无人机）在**编成表固定出生位**（约 (0,-20)，与 T-ASL 同一条起跑线） | 编成表 `formation.units[].position`（SDF 出生位，不按任务另编） |'),
    ('| T+0–11 | 规划器给出每条"集结地 → 占位点"的路径，平台按 A* 航迹机动；'
     '无人机爬升到 60 m 后直飞空域 | `plan.json assignments[].path` + 反馈轨迹 |',
     '| T+0–21 | 规划器给出每条"出发点 → 占位点"的路径（约 150 m），平台按 A* 航迹机动；'
     '无人机爬升到 60 m 后直飞空域 | `plan.json assignments[].path` + 反馈轨迹 |'),
    ('| T+11 | 占位组/门哨全部到位 → `control_established`，封控时段开始计时 | 行为层事件 |',
     '| T+21 | 占位组/门哨全部到位 → `control_established`，封控时段开始计时 | 行为层事件 |'),
    ('| T+11–191 | 在岗巡视 + 空中监视 + 警告/拦阻/授权放行（见 §4） | 行为层事件与指标 |',
     '| T+21–201 | 在岗巡视 + 空中监视 + 警告/拦阻/授权放行（见 §4） | 行为层事件与指标 |'),
    ('| `assembly_point` | 集结待机区中心（同时用于画面标注；平台实际出发点取自编成表） | `[-95,-60]` |',
     '| `assembly_point` | 出发点标注（平台实际出发点恒为编成表出生位，不随任务改） | `[-2.5,-19]` |'),
    ('→ `verdict=succeeded`，未授权进入 0，漏控率 0，拦截 1/1，覆盖率 0.96，\n'
     '  占位率 0.96，平均响应 1.0 s，控制建立 11 s，结束 191 s；空中监视 1 台 · 60 m。',
     '→ `verdict=succeeded`，未授权进入 0，漏控率 0，拦截 1/1，覆盖率 0.92，\n'
     '  占位率 0.92，平均响应 1.0 s，控制建立 21 s（进场约 150 m），结束 201 s；'
     '空中监视 1 台 · 60 m。'),
])

patch(DOC_HLD, [
    ('| T+0 | 6 台平台（3 轮式 + 2 履带 + 1 固定翼）在集结区（`assembly_point`，街区南侧约 85 m） | 编成表 `formation.units[].position` |',
     '| T+0 | 6 台平台（3 轮式 + 2 履带 + 1 固定翼）在**编成表固定出生位**（约 (0,-20)，与 T-SEC / T-ASL 同一条起跑线） | 编成表 `formation.units[].position`（SDF 出生位） |'),
    ('| T+0–12 | 规划器给出"集结地 → 阵位/预备队待机点"的路径，平台按 A* 航迹机动；固定翼爬升到 60 m |',
     '| T+0–23 | 规划器给出"出发点 → 阵位/预备队待机点"的路径（约 150 m），平台按 A* 航迹机动；固定翼爬升到 60 m |'),
    ('| T+12 | 4 个阵位到齐（≥ `min_on_post`=3）→ `control_established`，坚守时段开始计时 | 行为层事件 |',
     '| T+23 | 4 个阵位到齐（≥ `min_on_post`=3）→ `control_established`，坚守时段开始计时 | 行为层事件 |'),
    ('| T+12–162 | **在岗游走**：各阵位在自己前方左右踱步（±5 m、1.5 m/s），**空中观察席**绕要点定高盘旋（60 m、半径 45 m） | 反馈轨迹 + `patrol_*` / `air_*` 参数 |',
     '| T+23–173 | **在岗游走**：各阵位在自己前方左右踱步（±5 m、1.5 m/s），**空中观察席**绕要点定高盘旋（60 m、半径 45 m） | 反馈轨迹 + `patrol_*` / `air_*` 参数 |'),
    ('| T+62–67 | 第 1 次接替：预备队前出 P1，**到位后**原占位者才转预备队 | `handover_start` / `handover_complete` |',
     '| T+73–78 | 第 1 次接替：预备队前出 P1，**到位后**原占位者才转预备队 | `handover_start` / `handover_complete` |'),
    ('| T+112–120 | 第 2 次接替（P2） | 同上 |',
     '| T+123–131 | 第 2 次接替（P2） | 同上 |'),
    ('| T+162–174 | 坚守满 `hold_duration_s`=150 s → 撤离回集结区 | `withdraw_started` / `withdrawn` |',
     '| T+173–188 | 坚守满 `hold_duration_s`=150 s → 撤到街区南侧待命点 | `withdraw_started` / `withdrawn` |'),
    ('| T+174 | `hold_result` 结算：判定项、指标、阵位在位区间、时间线、桩判定清单 | 行为层事件 |',
     '| T+188 | `hold_result` 结算：判定项、指标、阵位在位区间、时间线、桩判定清单 | 行为层事件 |'),
    ('- `python -m interop.cli demo ... --max-ticks 300` → 判定 `succeeded`：\n'
     '  控制建立 T+12 s（4 个阵位、下限 3），坚守 150 s，控制保持率 1.0，控制中断 0 s，',
     '- `python -m interop.cli demo ... --max-ticks 320` → 判定 `succeeded`：\n'
     '  控制建立 T+23 s（4 个阵位、下限 3，进场约 150 m），坚守 150 s，控制保持率 1.0，控制中断 0 s，'),
    ('**要点全向覆盖 99.9%**（按阵位 45 m 探测圈统计，最差一拍仅 1 个方位缺口）；',
     '**要点全向覆盖 100%**（按阵位 45 m 探测圈统计，缺口 0 个方位）；'),
    ('  轮换 2 次（P1 62→67 s、P2 112→120 s，均到位才撤），',
     '  轮换 2 次（P1 73→78 s、P2 123→131 s，均到位才撤），'),
    ('  撤离按时完成（162→174 s），我方损失 0；桩判定 4 条 `verified=false`。',
     '  撤离按时完成（173→188 s，撤到街区南侧待命点），我方损失 0；桩判定 4 条 `verified=false`。'),
])

patch(README_INTEROP, [
    ('小十字路口 60×60 m 街区，2 段占位 + 2 个门哨 + 1 个机动组 + 1 架空中监视，'
     '2 条未授权目标 + 1 条授权目标）。',
     '小十字路口 60×60 m 街区（出发点为编成表固定出生位，与 T-ASL 一致），'
     '2 段占位 + 2 个门哨 + 1 个机动组 + 1 架空中监视，2 条未授权目标 + 1 条授权目标）。'),
])

patch(OUT_HLD, [
    ('| 控制建立 | T+12 s，在位 4 台（下限 3） | `hold_result.metrics` |',
     '| 控制建立 | T+23 s（进场约 150 m），在位 4 台（下限 3） | `hold_result.metrics` |'),
    ('| 要点全向覆盖 | 99.9%（按各阵位 45 m **圆形探测圈**统计要点一周，最差一拍 1 个方位缺口，判据门限 0.95） | `hold_result.metrics.observation_coverage_mean` |',
     '| 要点全向覆盖 | 100%（按各阵位 45 m **圆形探测圈**统计要点一周，缺口 0 个方位） | `hold_result.metrics.observation_coverage_mean` |'),
    ('| 至少 1 次"到位才撤"的轮换 | 2 次：P1 62→67 s、P2 112→120 s，均 `arrival_before_departure=true` | `hold_result.handovers` |',
     '| 至少 1 次"到位才撤"的轮换 | 2 次：P1 73→78 s、P2 123→131 s，均 `arrival_before_departure=true` | `hold_result.handovers` |'),
    ('| 撤离 | 坚守满 150 s → T+162 撤离 → T+174 回到集结区（时限 45 s） | 时间线 `withdraw_started` / `withdrawn` |',
     '| 撤离 | 坚守满 150 s → T+173 撤离 → T+188 撤到街区南侧待命点（时限 45 s） | 时间线 `withdraw_started` / `withdrawn` |'),
])

patch(OUT_SEC, [
    ('> 2026-11-03：样例已搬到**小十字路口建筑区**（`asl_city` 的 (-95,-145) 一带），\n'
     '> 封控区改为 60×60 m 街区；`区域封控_*.png`、`总览_*.png` 是搬迁前的历史截图，\n'
     '> 新位置的画面见 `街区封控_在位.png` / `街区封控_全页.png`。',
     '> 2026-11-03：样例已搬到**小十字路口建筑区**（`asl_city` 的 (-95,-145) 一带），\n'
     '> 封控区改为 60×60 m 街区；出发点统一为编成表出生位（约 (0,-20)，与 T-ASL 一致）。\n'
     '> `区域封控_*.png`、`总览_*.png` 是搬迁前的历史截图，新位置的画面见\n'
     '> `街区封控_在位.png` / `街区封控_全页.png`。'),
])
