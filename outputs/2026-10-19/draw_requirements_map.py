"""Draw a requirements map, not an implementation architecture."""
from pathlib import Path
from html import escape
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 1600, 1480
canvas = Image.new("RGB", (W, H), "#f8fafc")
draw = ImageDraw.Draw(canvas)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       '<rect width="100%" height="100%" fill="#f8fafc"/>']


def font(size):
    return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)


def text(x, y, value, size=26, fill="#26364b"):
    draw.text((x, y), value, font=font(size), fill=fill, anchor="lt")
    svg.append(f'<text x="{x}" y="{y+size}" font-size="{size}" font-family="Microsoft YaHei, sans-serif" fill="{fill}">{escape(value)}</text>')


def rect(x, y, width, height, fill, outline, radius=18):
    draw.rounded_rectangle((x, y, x+width, y+height), radius=radius, fill=fill, outline=outline, width=2)
    svg.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{fill}" stroke="{outline}" stroke-width="2"/>')


def line(points, fill="#92a1b4", width=2):
    draw.line(points, fill=fill, width=width)
    pts = " ".join(f"{x},{y}" for x,y in points)
    svg.append(f'<polyline points="{pts}" fill="none" stroke="{fill}" stroke-width="{width}"/>')


def card(x, y, width, height, number, title, subtitle, fill, border, accent):
    rect(x, y, width, height, fill, border)
    rect(x+24, y+24, 86, 48, accent, accent, 10)
    text(x+38, y+32, number, 28, "#ffffff")
    text(x+130, y+29, title, 31, accent)
    text(x+28, y+89, subtitle, 22, "#66788d")
    line([(x+28,y+127),(x+width-28,y+127)], border)


text(70, 45, "需求指标关系图", 46, "#183453")
text(72, 111, "按原文功能分组，呈现职责关联与验收边界", 26, "#63758b")
rect(70, 168, 1460, 59, "#edf1f6", "#d8e0ea", 12)
text(92, 182, "信息来源与交互对象：上层编组模块、想定配置、导调事件、单平台智能体、仿真引擎", 25, "#415771")

card(70, 270, 700, 460, "2.1", "编组接口与动态重规划", "接收信息，识别变化与执行偏差", "#edf5ff", "#9abce8", "#2861a2")
text(98, 422, "（1）订阅编组树、分组、约束与目标", 26)
text(132, 460, "编组信息接收时延 ≤50ms", 26, "#2861a2")
text(98, 510, "（2）感知编组变化并启动重规划", 26)
text(98, 560, "（3）接入想定配置、导调与动态事件", 26)
text(98, 610, "（4）判定执行偏差；失败或超时后", 26)
text(132, 648, "在编组范围内重新分配", 26)

card(830, 270, 700, 460, "2.2", "子任务分发与闭环交互", "逐平台输出，接收反馈，检验时序冲突", "#edf5ff", "#9abce8", "#2861a2")
text(858, 422, "（1）逐平台独立下发子任务与时序", 26)
text(858, 472, "（2）≥15台；双向通信；总耗时 ≤800ms", 26, "#2861a2")
text(892, 514, "每个平台输出四项：", 25)
text(892, 551, "子任务／任务时序／时间窗口／协同约束", 25)
text(858, 610, "（3）动态场景20回合内", 26)
text(892, 648, "子任务时序冲突消解率 ≥95%", 26, "#2861a2")

card(70, 850, 700, 450, "2.3", "动态适配与能力约束", "规定适用范围、变化条件及输出边界", "#f1efff", "#b2a7e8", "#6654b6")
text(98, 1002, "（1）≥4类平台；1～5台数量动态增减", 25)
text(132, 1039, "新增接入、损毁失联处置及动态重构", 25)
text(98, 1087, "（3）≥5类任务；差异化分配与调度", 25)
text(98, 1135, "（4）≥3类优化目标切换：", 25)
text(132, 1172, "任务完成时效／暴露风险／能耗代价", 25)
text(98, 1220, "（5）校验续航、载荷、传感器、运动性能", 25)
text(132, 1257, "不输出超出平台能力边界的子任务方案", 24)

card(830, 850, 700, 450, "2.4", "双引擎对接与评估分析", "支撑消息交互、可视化与证据留存", "#eaf7f8", "#8ec8ce", "#26747d")
text(858, 1002, "（1）ROS2连接Gazebo与UE5消息交互", 25)
text(892, 1039, "时间戳对齐；同步误差 ≤50ms", 26, "#26747d")
text(858, 1094, "（2）UE5展示编组关系、子任务与时序", 25)
text(858, 1149, "（3）采集全链路数据并自动统计指标", 25)
text(892, 1190, "编组 — 任务分解 — 单平台执行", 25)

# Relationships between requirement groups, not runtime or deployment wiring.
line([(770,505),(830,505)], "#8296ad", 3)
line([(780,497),(770,505),(780,513)], "#8296ad", 3)
line([(820,497),(830,505),(820,513)], "#8296ad", 3)
text(773, 455, "衔接", 20, "#63758b")
line([(420,850),(420,730)], "#9a8ec9", 3)
line([(411,741),(420,730),(429,741)], "#9a8ec9", 3)
rect(348, 763, 144, 43, "#f8fafc", "#f8fafc", 7)
text(362, 771, "适用条件", 24, "#7766ad")
line([(1180,850),(1180,730)], "#7aa8b3", 3)
line([(1171,741),(1180,730),(1189,741)], "#7aa8b3", 3)
rect(1092, 763, 176, 43, "#f8fafc", "#f8fafc", 7)
text(1105, 771, "记录与呈现", 24, "#4d8893")

text(73, 1340, "连线表示条款关联，不表示进程划分、部署架构或固定执行顺序。", 24, "#52667e")
text(73, 1384, "验收口径待确认：接收时延≠同步误差；总耗时起止点、20回合与消解率分母需定义。", 23, "#52667e")
text(73, 1425, "共14条技术子指标；2.3沿用原文编号（1）（3）（4）（5）。图中数值均为要求，非实测结果。", 22, "#728196")

svg.append("</svg>")
OUT.mkdir(parents=True, exist_ok=True)
canvas.save(OUT / "需求指标关系图.png")
(OUT / "需求指标关系图.svg").write_text("\n".join(svg), encoding="utf-8")
print("Created PNG and SVG requirements maps")
