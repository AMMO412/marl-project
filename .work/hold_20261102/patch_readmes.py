# -*- coding: utf-8 -*-
"""更新两份结果 README：坐标搬到小十字路口街区后的数字与说明。"""
import io

HLD = 'outputs/要点坚守_20261102/README.md'
SEC = 'outputs/区域封控_20261031/README.md'


def patch(path, pairs, crlf=False):
    text = io.open(path, encoding='utf-8', newline='').read()
    if '\r\n' in text:
        pairs = [(a.replace('\n', '\r\n'), b.replace('\n', '\r\n'))
                 for a, b in pairs]
    for old, new in pairs:
        if old not in text:
            raise SystemExit('not found in %s: %s' % (path, old[:60]))
        text = text.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='').write(text)
    print('patched', path)


patch(HLD, [
    ('> 口径：**本地替身 + 行为状态机 + 4.1 输入回放**，不是真实平台 / ROS / Gazebo 联调。',
     '> 口径：**本地替身 + 行为状态机 + 4.1 输入回放**，不是真实平台 / ROS / Gazebo 联调。\n'
     '> 位置：2026-11-03 起样例搬到**小十字路口建筑区**（`asl_city` 的 (-95,-145) 一带，'
     '四栋楼围出的街区），本文数字与截图均为搬迁后重跑。'),
    ('| 控制建立 | T+16 s，在位 4 台（下限 3） | `hold_result.metrics` |',
     '| 控制建立 | T+12 s，在位 4 台（下限 3） | `hold_result.metrics` |'),
    ('| 要点全向覆盖 | 100%（按各阵位 45 m **圆形探测圈**统计要点一周，缺口 0 个方位） | `hold_result.metrics.observation_coverage_mean` |',
     '| 要点全向覆盖 | 99.9%（按各阵位 45 m **圆形探测圈**统计要点一周，最差一拍 1 个方位缺口，判据门限 0.95） | `hold_result.metrics.observation_coverage_mean` |'),
    ('| 至少 1 次"到位才撤"的轮换 | 2 次：P1 66→69 s、P2 116→124 s，均 `arrival_before_departure=true` | `hold_result.handovers` |',
     '| 至少 1 次"到位才撤"的轮换 | 2 次：P1 62→67 s、P2 112→120 s，均 `arrival_before_departure=true` | `hold_result.handovers` |'),
    ('| 撤离 | 坚守满 150 s → T+166 撤离 → T+178 到位（时限 45 s） | 时间线 `withdraw_started` / `withdrawn` |',
     '| 撤离 | 坚守满 150 s → T+162 撤离 → T+174 回到集结区（时限 45 s） | 时间线 `withdraw_started` / `withdrawn` |'),
    ('| [工作台_要点坚守_120s.png](工作台_要点坚守_120s.png) | “要点坚守”页签 T+120 s：要点、4 个阵位（含朝向与在位编号）、4 条威胁扇区、**跟随在位平台的探测圈**、空中观察席盘旋航线、预备队、在位甘特、逐项判定、桩判定清单、过程时间线 |',
     '| [工作台_要点坚守_120s.png](工作台_要点坚守_120s.png) | “要点坚守”页签 T+120 s（小十字路口街区）：要点、4 个阵位（含朝向与在位编号）、4 条威胁扇区、**跟随在位平台的探测圈**、空中观察席盘旋航线、预备队、在位甘特、逐项判定、桩判定清单、过程时间线；底图为楼体/道路 |'),
])

patch(SEC, [
    ('> 依据：《无人集群编队五类任务定义》2.2 T-SEC（区域封控）与 1.4/1.5 的判定、结算口径。',
     '> 2026-11-03：样例已搬到**小十字路口建筑区**（`asl_city` 的 (-95,-145) 一带），'
     '封控区改为 60×60 m 街区；`区域封控_*.png`、`总览_*.png` 是搬迁前的历史截图，'
     '新位置的画面见 `街区封控_在位.png` / `街区封控_全页.png`。\n'
     '>\n'
     '> 依据：《无人集群编队五类任务定义》2.2 T-SEC（区域封控）与 1.4/1.5 的判定、结算口径。'),
])
