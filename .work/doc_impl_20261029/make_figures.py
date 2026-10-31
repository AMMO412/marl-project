# -*- coding: utf-8 -*-
"""Build the two schematic figures and crop the three workbench screenshots."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r"D:\Desktop\MARL项目")
OUT = ROOT / ".work" / "doc_impl_20261029" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
SHOTS = ROOT / "outputs" / "工作台_20261029_多类型兵力包"

FONT_CN = r"C:\Windows\Fonts\msyh.ttc"
FONT_CN_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_HEI = r"C:\Windows\Fonts\simhei.ttf"

INK = (34, 51, 49)
MUTED = (104, 122, 114)
GREEN = (31, 95, 74)
GREEN_LIGHT = (237, 246, 241)
BLUE = (63, 111, 163)
BLUE_LIGHT = (235, 242, 249)
ORANGE = (176, 130, 62)
ORANGE_LIGHT = (250, 245, 235)
GRAY = (120, 134, 128)
LINE = (196, 208, 200)
WHITE = (255, 255, 255)


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap(draw, text, fnt, width):
    """Wrap CJK by character, Latin by word; never split a Latin token."""
    tokens, buf = [], ""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isascii() and (ch.isalnum() or ch in "._-/%+·"):
            buf += ch
            i += 1
            continue
        if buf:
            tokens.append(buf)
            buf = ""
        tokens.append(ch)
        i += 1
    if buf:
        tokens.append(buf)

    lines, line = [], ""
    for tok in tokens:
        candidate = line + tok
        if draw.textlength(candidate, font=fnt) <= width:
            line = candidate
            continue
        if line:
            lines.append(line.rstrip())
        # Latin token longer than width: hard split as a last resort
        while draw.textlength(tok, font=fnt) > width:
            cut = len(tok)
            while cut > 1 and draw.textlength(tok[:cut], font=fnt) > width:
                cut -= 1
            lines.append(tok[:cut])
            tok = tok[cut:]
        line = tok
    if line:
        lines.append(line.rstrip())
    return lines


def arrow(draw, xy0, xy1, color=GRAY, width=5, head=18, dash=None):
    x0, y0 = xy0
    x1, y1 = xy1
    if dash:
        total = math.hypot(x1 - x0, y1 - y0)
        step = dash[0] + dash[1]
        n = int(total // step) + 1
        for i in range(n):
            a = min(1.0, (i * step) / total)
            b = min(1.0, (i * step + dash[0]) / total)
            draw.line([x0 + (x1 - x0) * a, y0 + (y1 - y0) * a,
                       x0 + (x1 - x0) * b, y0 + (y1 - y0) * b], fill=color, width=width)
    else:
        draw.line([x0, y0, x1, y1], fill=color, width=width)
    ang = math.atan2(y1 - y0, x1 - x0)
    pts = [(x1, y1),
           (x1 - head * math.cos(ang - 0.42), y1 - head * math.sin(ang - 0.42)),
           (x1 - head * math.cos(ang + 0.42), y1 - head * math.sin(ang + 0.42))]
    draw.polygon(pts, fill=color)


# ------------------------------------------------------------------
# 图 1 系统组成与运行闭环
# ------------------------------------------------------------------
def figure_architecture():
    W, H = 2240, 900
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f_layer = font(FONT_HEI, 42)
    f_en = font(FONT_CN, 22)
    f_bullet = font(FONT_CN, 29)
    f_small = font(FONT_CN, 25)

    blocks = [
        ("① 任务输入", "INPUT", GREEN, [
            "任务指令：目标、时间窗、效果",
            "兵力包与角色（6 台四类平台）",
            "SDF 初始状态：位姿与尺寸",
            "场景几何、ROE 与规则约束",
        ]),
        ("② 规划", "PLANNING", (43, 88, 120), [
            "能力过滤：角色载荷、续航",
            "代价打分 → 分配求解",
            "时序排程 → 冲突消解",
            "方案校验 → 滚动重规划",
        ]),
        ("③ 指令与执行", "COMMAND & MOTION", (58, 112, 92), [
            "command_id / attempt 幂等",
            "地面 A* 绕障、空中直飞",
            "行为状态机（五个阶段）",
            "进度、位姿、弹药实时反馈",
        ]),
        ("④ 效果判定", "ADJUDICATION", ORANGE, [
            "毁伤 / 压制 / 夺占三类效果",
            "必需项逐项结算",
            "辅助指标：命中率、覆盖、控制",
            "评估接口（默认桩判定）",
        ]),
        ("⑤ 回放与报告", "REPLAY", (90, 96, 120), [
            "轨迹、事件与阶段时间条",
            "地图：道路、建筑、绕障证据",
            "report.json / trace.jsonl",
            "三类效果可切换对照",
        ]),
    ]
    bw, bh, gap, top = 392, 500, 46, 110
    x = 50
    centers = []
    for (title, en, color, bullets) in blocks:
        y = top
        d.rounded_rectangle([x, y, x + bw, y + bh], radius=16, fill=WHITE, outline=LINE, width=2)
        d.rounded_rectangle([x, y, x + bw, y + 104], radius=16, fill=color)
        d.rectangle([x, y + 76, x + bw, y + 104], fill=color)
        d.text((x + 22, y + 12), title, font=f_layer, fill=WHITE)
        d.text((x + 22, y + 64), en, font=f_en, fill=(235, 245, 240))
        ty = y + 136
        for b in bullets:
            lines = wrap(d, b, f_bullet, bw - 60)
            d.ellipse([x + 24, ty + 11, x + 34, ty + 21], fill=color)
            for j, line in enumerate(lines):
                d.text((x + 46, ty + j * 38), line, font=f_bullet, fill=INK)
            ty += 38 * len(lines) + 24
        centers.append(x + bw // 2)
        x += bw + gap

    for i in range(4):
        x0 = 50 + (i + 1) * bw + i * gap
        arrow(d, (x0 + 10, top + bh // 2), (x0 + gap - 12, top + bh // 2), GRAY, 5, 17)

    # feedback loop
    yb = top + bh + 42
    d.line([centers[3], top + bh + 8, centers[3], yb], fill=ORANGE, width=4)
    d.line([centers[1], top + bh + 8, centers[1], yb], fill=ORANGE, width=4)
    d.line([centers[1], yb, centers[3], yb], fill=ORANGE, width=4)
    arrow(d, (centers[1] + 2, yb), (centers[1] + 2, top + bh + 10), ORANGE, 4, 14)
    d.text((centers[1] + 22, yb + 10),
           "失败 / 超时 / 进度偏差 / 成员变化 / 周期更新 → 重新规划",
           font=f_small, fill=ORANGE)

    strip_y = H - 92
    d.rounded_rectangle([50, strip_y, W - 50, strip_y + 62], radius=12,
                        fill=(247, 249, 247), outline=LINE, width=2)
    d.text((72, strip_y + 15),
           "统一事实源：scenario.json（输入）· report.json / trace.jsonl（运行）· behavior events（阶段与结果）"
           "　界面只读这些记录，不另造数据",
           font=f_small, fill=MUTED)

    img.save(OUT / "fig1_architecture.png", dpi=(220, 220))
    print("fig1", img.size)


# ------------------------------------------------------------------
# 图 2 任务阶段时序（毁伤运行）
# ------------------------------------------------------------------
def figure_timeline():
    W, H = 2240, 880
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f_time = font(FONT_CN, 24)
    f_stage = font(FONT_CN, 30)
    f_title = font(FONT_HEI, 30)
    f_small = font(FONT_CN, 24)
    f_note = font(FONT_CN, 23)

    left, right = 430, W - 110
    t0, t1 = 0, 300
    x_of = lambda t: left + (t - t0) / (t1 - t0) * (right - left)
    top_labels = 90
    axis_y = 700

    # grid + axis
    for t in range(0, 301, 25):
        x = x_of(t)
        d.line([x, top_labels + 60, x, axis_y], fill=(240, 243, 239), width=2)
    d.line([left, axis_y, right, axis_y], fill=GRAY, width=3)
    for t in range(0, 301, 50):
        x = x_of(t)
        d.line([x, axis_y, x, axis_y + 10], fill=GRAY, width=2)
        label = str(t)
        tw = d.textlength(label, font=f_time)
        d.text((x - tw / 2, axis_y + 16), label, font=f_time, fill=MUTED)
    tw = d.textlength("仿真时间 / s", font=f_small)
    d.text((right - tw, axis_y + 52), "仿真时间 / s", font=f_small, fill=MUTED)

    stages = [
        ("机动集结", 1, 165, GREEN, 220),
        ("等待 / 到位", 165, 166, (122, 150, 132), 292),
        ("执行动作", 166, 237, BLUE, 364),
        ("结果确认", 237, 258, ORANGE, 436),
        ("撤离收拢", 258, 299, (104, 112, 136), 508),
    ]
    bar_h = 44
    for name, a, b, color, y in stages:
        d.text((70, y + 2), name, font=f_stage, fill=INK)
        d.text((70, y + 44), "%d–%d s" % (a, b), font=f_small, fill=MUTED)
        x0, x1 = x_of(a), x_of(b)
        if x1 - x0 < 6:
            x1 = x0 + 6
        d.rounded_rectangle([x0, y, x1, y + bar_h], radius=8, fill=color)
        # duration outside the bar
        dur = "%d s" % (b - a)
        d.text((x1 + 14, y + 6), dur, font=f_small, fill=MUTED)

    # milestone lines
    marks = [(1, "受领任务", 0), (165.5, "全员到位 / 突击开始", 0),
             (237, "动作结束", 1), (258, "评估回传", 0), (299, "撤离完成", 1)]
    for t, label, row in marks:
        x = x_of(t)
        d.line([x, top_labels + 58, x, axis_y - 2], fill=(168, 182, 172), width=2, )
        d.ellipse([x - 9, axis_y - 9, x + 9, axis_y + 9], fill=ORANGE)
        tw = d.textlength(label, font=f_small)
        ly = top_labels - 14 + row * 34
        d.text((x - tw / 2, ly), label, font=f_small, fill=INK)
        tm = str(int(t)) if float(t).is_integer() else "165/166"
        tw2 = d.textlength(tm, font=f_small)
        d.text((x - tw2 / 2, ly + 30), tm + " s", font=f_small, fill=ORANGE)

    d.text((70, 800),
           "注：时刻取自运行 workbench_20261029_181813_611337 的行为事件；1 个仿真步 = 1 s。"
           "单次运行，不代表统计分布。",
           font=f_note, fill=MUTED)

    img.save(OUT / "fig2_timeline.png", dpi=(220, 220))
    print("fig2", img.size)


def crop(name, box, out_name):
    img = Image.open(SHOTS / name)
    part = img.crop(box)
    part.save(OUT / out_name)
    print(out_name, part.size)


if __name__ == "__main__":
    figure_architecture()
    figure_timeline()
    crop("global.png", (240, 350, 1160, 1125), "fig3_global.png")
    crop("approach.png", (240, 385, 1160, 1165), "fig4_approach.png")
    crop("process.png", (240, 330, 1330, 1125), "fig5_process.png")


