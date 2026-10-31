# -*- coding: utf-8 -*-
"""Rebuild figure 1 as a vertical five-layer diagram (readable at 14-15 cm width)."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(r"D:\Desktop\MARL项目\.work\doc_impl_20261029\figures")
FONT_CN = r"C:\Windows\Fonts\msyh.ttc"
FONT_HEI = r"C:\Windows\Fonts\simhei.ttf"
INK = (34, 51, 49)
MUTED = (100, 118, 110)
GREEN = (31, 95, 74)
BLUE = (43, 88, 120)
TEAL = (52, 112, 96)
ORANGE = (166, 122, 56)
PURPLE = (86, 92, 118)
LINE = (198, 210, 202)
WHITE = (255, 255, 255)


def f(path, size):
    return ImageFont.truetype(path, size)


def arrow(d, x0, y0, x1, y1, color=MUTED, width=5, head=14):
    d.line([x0, y0, x1, y1], fill=color, width=width)
    ang = math.atan2(y1 - y0, x1 - x0)
    pts = [(x1, y1),
           (x1 - head * math.cos(ang - 0.45), y1 - head * math.sin(ang - 0.45)),
           (x1 - head * math.cos(ang + 0.45), y1 - head * math.sin(ang + 0.45))]
    d.polygon(pts, fill=color)


def main():
    W = 1600
    H = 1500
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f_num = f(FONT_HEI, 40)
    f_title = f(FONT_HEI, 40)
    f_body = f(FONT_CN, 32)
    f_en = f(FONT_CN, 22)
    f_note = f(FONT_CN, 24)

    rows = [
        ("①", "任务输入", "INPUT", GREEN,
         ["任务指令：目标、时间窗、效果", "兵力包与角色（6 台四类平台）",
          "SDF 初始状态：位姿与尺寸", "场景几何、交战规则与约束"]),
        ("②", "规划", "PLANNING", BLUE,
         ["能力过滤：角色载荷、续航", "代价打分 → 分配求解",
          "时序排程 → 冲突消解", "方案校验 → 滚动重规划"]),
        ("③", "指令与执行", "COMMAND & MOTION", TEAL,
         ["command_id / attempt 幂等下发", "地面 A* 绕障、空中直飞",
          "行为状态机（机动→到位→执行）", "进度、位姿、弹药实时反馈"]),
        ("④", "效果判定", "ADJUDICATION", ORANGE,
         ["毁伤 / 压制 / 夺占三类效果", "必需项逐项结算",
          "辅助指标：命中率、覆盖、控制", "评估接口（默认桩判定）"]),
        ("⑤", "回放与报告", "REPLAY", PURPLE,
         ["轨迹、事件与阶段时间条", "地图：道路、建筑、绕障证据",
          "report.json / trace.jsonl", "三类效果切换对照"]),
    ]

    left, right = 90, W - 90
    y = 60
    card_h = 208
    gap = 64
    centers = []
    for num, title, en, color, bullets in rows:
        d.rounded_rectangle([left, y, right, y + card_h], radius=14,
                            fill=(252, 253, 252), outline=LINE, width=2)
        # 左侧编号色块
        d.rounded_rectangle([left, y, left + 150, y + card_h], radius=14, fill=color)
        d.rectangle([left + 100, y, left + 150, y + card_h], fill=color)
        d.text((left + 42, y + 52), num, font=f_num, fill=WHITE)
        # 标题
        d.text((left + 178, y + 26), title, font=f_title, fill=color)
        d.text((left + 180, y + 76), en, font=f_en, fill=MUTED)
        # 2×2 要点
        col_w = (right - left - 200) // 2
        for i, b in enumerate(bullets):
            cx = left + 178 + (i % 2) * col_w
            cy = y + 112 + (i // 2) * 46
            d.ellipse([cx, cy + 12, cx + 10, cy + 22], fill=color)
            d.text((cx + 20, cy), b, font=f_body, fill=INK)
        centers.append((left + 75, y + card_h // 2))
        if num != "⑤":
            arrow(d, (left + 75), y + card_h + 6, (left + 75), y + card_h + gap - 8,
                  MUTED, 4, 12)
        y += card_h + gap

    # 底部：闭环说明 + 事实源
    d.text((left, H - 104),
           "反馈闭环：失败 / 超时 / 进度偏差 / 成员变化 / 周期更新 → 回到②重新规划",
           font=f_note, fill=ORANGE)
    d.text((left, H - 54),
           "统一事实源：scenario.json（输入）· report.json / trace.jsonl（运行）· behavior events（阶段与结果）",
           font=f_note, fill=MUTED)
    img.save(OUT / "fig1_architecture.png", dpi=(200, 200))
    print("saved", img.size)


if __name__ == "__main__":
    main()


