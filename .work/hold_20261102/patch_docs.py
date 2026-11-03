# -*- coding: utf-8 -*-
"""把两份任务文档里与"样例位置"相关的数字/坐标改到小十字路口建筑区。

用文件而不是 PowerShell here-string：后者会把反引号当转义符，把 Markdown 的
`code` 标记吃掉。
"""
import io

DOC_SEC = 'docs/区域封控任务_20261031.md'
DOC_HLD = 'docs/要点坚守任务_20261102.md'
README_INTEROP = 'planning_middle_demo/interop/README.md'


def patch(path, pairs):
    text = io.open(path, encoding='utf-8', newline='').read()
    # 这些 md 有的是 CRLF：多行 old/new 里的 \n 要跟着换，否则永远匹配不上。
    if '\r\n' in text:
        pairs = [(old.replace('\n', '\r\n'), new.replace('\n', '\r\n'))
                 for old, new in pairs]
    for old, new in pairs:
        if old not in text:
            raise SystemExit('not found in %s:\n%s' % (path, old[:80]))
        text = text.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='').write(text)
    print('patched', path)


patch(DOC_SEC, [
    ('| T+0 | 6 台平台（5 台地面 + 1 架无人机）在集结待机区待机'
     '（`assembly_point`，约 150–220 m 外） | 编成表 `formation.units[].position` |',
     '| T+0 | 6 台平台（5 台地面 + 1 架无人机）在集结待机区待机'
     '（`assembly_point`，街区南侧约 55 m） | 编成表 `formation.units[].position` |'),
    ('| T+0–23 | 规划器给出每条"集结地 → 占位点"的路径，平台按 A* 航迹机动；'
     '无人机爬升到 60 m 后直飞空域 | `plan.json assignments[].path` + 反馈轨迹 |',
     '| T+0–11 | 规划器给出每条"集结地 → 占位点"的路径，平台按 A* 航迹机动；'
     '无人机爬升到 60 m 后直飞空域 | `plan.json assignments[].path` + 反馈轨迹 |'),
    ('| T+23 | 占位组/门哨全部到位 → `control_established`，封控时段开始计时 | 行为层事件 |',
     '| T+11 | 占位组/门哨全部到位 → `control_established`，封控时段开始计时 | 行为层事件 |'),
    ('| T+23–203 | 在岗巡视 + 空中监视 + 警告/拦阻/授权放行（见 §4） | 行为层事件与指标 |',
     '| T+11–191 | 在岗巡视 + 空中监视 + 警告/拦阻/授权放行（见 §4） | 行为层事件与指标 |'),
    ('| `intercept_post` | 机动组待机点（缺省多边形重心） | `[95,45]` |',
     '| `intercept_post` | 机动组待机点（缺省多边形重心） | `[-95,-145]` |'),
    ('| `assembly_point` | 集结待机区中心（同时用于画面标注；平台实际出发点取自编成表） | `[0,-46]` |',
     '| `assembly_point` | 集结待机区中心（同时用于画面标注；平台实际出发点取自编成表） | `[-95,-60]` |'),
    ('  → `verdict=succeeded`，未授权进入 0，漏控率 0，拦截 1/1，覆盖率 0.68，\n'
     '  占位率 0.94，平均响应 1.0 s，控制建立 23 s，结束 203 s；空中监视 1 台 · 60 m。',
     '  → `verdict=succeeded`，未授权进入 0，漏控率 0，拦截 1/1，覆盖率 0.96，\n'
     '  占位率 0.96，平均响应 1.0 s，控制建立 11 s，结束 191 s；空中监视 1 台 · 60 m。'),
])

patch(README_INTEROP, [
    ('140×90 m 区域，2 段占位 + 2 个门哨 + 1 个机动组，2 条未授权目标 + 1 条授权目标）。',
     '小十字路口 60×60 m 街区，2 段占位 + 2 个门哨 + 1 个机动组 + 1 架空中监视，'
     '2 条未授权目标 + 1 条授权目标）。'),
])

patch(DOC_HLD, [
    ('| T+0 | 6 台平台（3 轮式 + 2 履带 + 1 固定翼）在集结区（`assembly_point`，约 100–120 m 外） | 编成表 `formation.units[].position` |',
     '| T+0 | 6 台平台（3 轮式 + 2 履带 + 1 固定翼）在集结区（`assembly_point`，街区南侧约 85 m） | 编成表 `formation.units[].position` |'),
    ('| T+0–16 | 规划器给出"集结地 → 阵位/预备队待机点"的路径，平台按 A* 航迹机动；固定翼爬升到 60 m |',
     '| T+0–12 | 规划器给出"集结地 → 阵位/预备队待机点"的路径，平台按 A* 航迹机动；固定翼爬升到 60 m |'),
    ('| T+16 | 4 个阵位到齐（≥ `min_on_post`=3）→ `control_established`，坚守时段开始计时 | 行为层事件 |',
     '| T+12 | 4 个阵位到齐（≥ `min_on_post`=3）→ `control_established`，坚守时段开始计时 | 行为层事件 |'),
    ('| T+16–166 | **在岗游走**：各阵位在自己前方左右踱步（±5 m、1.5 m/s），**空中观察席**绕要点定高盘旋（60 m、半径 45 m） | 反馈轨迹 + `patrol_*` / `air_*` 参数 |',
     '| T+12–162 | **在岗游走**：各阵位在自己前方左右踱步（±5 m、1.5 m/s），**空中观察席**绕要点定高盘旋（60 m、半径 45 m） | 反馈轨迹 + `patrol_*` / `air_*` 参数 |'),
    ('| T+55 / 95 / 125 / 150 | 敌方进攻输入事件（N 试探 → N 突击 ratio 1.6 → E 试探 → **S 后方试探**） | `enemy_events` |',
     '| T+55 / 95 / 125 / 150 | 敌方进攻输入事件（N 试探 → N 突击 ratio 1.6 → E 试探 → **S 后方试探**） | `enemy_events` |'),
    ('| T+66–69 | 第 1 次接替：预备队前出 P1，**到位后**原占位者才转预备队 | `handover_start` / `handover_complete` |',
     '| T+62–67 | 第 1 次接替：预备队前出 P1，**到位后**原占位者才转预备队 | `handover_start` / `handover_complete` |'),
    ('| T+116–124 | 第 2 次接替（P2） | 同上 |',
     '| T+112–120 | 第 2 次接替（P2） | 同上 |'),
    ('| T+166–178 | 坚守满 `hold_duration_s`=150 s → 开始撤离 → 到达撤离点 | `withdraw_started` / `withdrawn` |',
     '| T+162–174 | 坚守满 `hold_duration_s`=150 s → 撤离回集结区 | `withdraw_started` / `withdrawn` |'),
    ('| T+178 | `hold_result` 结算：判定项、指标、阵位在位区间、时间线、桩判定清单 | 行为层事件 |',
     '| T+174 | `hold_result` 结算：判定项、指标、阵位在位区间、时间线、桩判定清单 | 行为层事件 |'),
    ('- `python -m interop.cli demo ... --max-ticks 300` → 判定 `succeeded`：\n'
     '  控制建立 T+16 s（4 个阵位、下限 3），坚守 150 s，控制保持率 1.0，控制中断 0 s，',
     '- `python -m interop.cli demo ... --max-ticks 300` → 判定 `succeeded`：\n'
     '  控制建立 T+12 s（4 个阵位、下限 3），坚守 150 s，控制保持率 1.0，控制中断 0 s，'),
    ('**要点全向覆盖 100%**（按阵位 45 m 探测圈统计，缺口 0 个方位）；',
     '**要点全向覆盖 99.9%**（按阵位 45 m 探测圈统计，最差一拍仅 1 个方位缺口）；'),
    ('  轮换 2 次（P1 66→69 s、P2 116→124 s，均到位才撤），',
     '  轮换 2 次（P1 62→67 s、P2 112→120 s，均到位才撤），'),
    ('  撤离按时完成（166→178 s），我方损失 0；桩判定 4 条 `verified=false`。',
     '  撤离按时完成（162→174 s），我方损失 0；桩判定 4 条 `verified=false`。'),
])
