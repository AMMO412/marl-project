"""Reorganize the supplied five-layer sketch and clause labels.

This illustrates requirement responsibilities, not a new algorithm or deployment.
"""
from pathlib import Path
from html import escape
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 1800, 1740
canvas = Image.new("RGB", (W, H), "#f8fafc")
draw = ImageDraw.Draw(canvas)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">', '<rect width="100%" height="100%" fill="#f8fafc"/>']


def text(x, y, value, size=27, fill="#26364b"):
    face = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
    draw.text((x,y), value, font=face, fill=fill, anchor="lt")
    svg.append(f'<text x="{x}" y="{y+size}" font-size="{size}" font-family="Microsoft YaHei, sans-serif" fill="{fill}">{escape(value)}</text>')


def rect(x,y,w,h,fill,outline="#bac9da",r=16):
    draw.rounded_rectangle((x,y,x+w,y+h), radius=r, fill=fill, outline=outline, width=2)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{outline}" stroke-width="2"/>')


def line(points, color="#7392b5", width=3):
    draw.line(points, fill=color, width=width)
    pts=" ".join(f"{x},{y}" for x,y in points)
    svg.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}"/>')


def arrow(points,color="#7392b5",width=3):
    line(points,color,width)
    x,y=points[-1]; px,py=points[-2]
    if x==px:
        k=1 if y>py else -1
        head=[(x-9,y-12*k),(x,y),(x+9,y-12*k)]
    else:
        k=1 if x>px else -1
        head=[(x-12*k,y-9),(x,y),(x-12*k,y+9)]
    line(head,color,width)


def layer(y,h,index,title,lines,purple=False):
    fill, border, accent=("#f0edff","#afa3e4","#6551b2") if purple else ("#eaf3ff","#97b8e3","#285f9e")
    rect(210,y,900,h,fill,border)
    rect(234,y+18,65,43,accent,accent,9)
    text(245,y+25,index,25,"#ffffff")
    text(318,y+21,title,31,accent)
    for n,entry in enumerate(lines):
        text(239,y+77+n*39,entry,26)


def note(y,h,title,lines):
    rect(1210,y,520,h,"#ffffff","#d0dbe7",12)
    text(1233,y+18,title,25,"#435c79")
    for n,entry in enumerate(lines):
        text(1233,y+61+n*35,entry,23,"#596d84")


text(70,35,"系统功能关系与指标归属",43,"#183453")
text(73,96,"沿用原图五层结构：主业务链路、反馈关系、候选学习工具与横向支撑",26,"#63758b")

rect(210,160,900,76,"#f0eee9","#b7b3aa",14)
text(251,180,"上层编组模块 ／ 想定配置 ／ 导调与动态事件",29,"#5d5b56")
arrow([(660,237),(660,280)])

layer(280,151,"L1","信息接入与格式适配",[
    "接收编组树、分组、约束、目标以及配置与事件输入",
    "回答：外部信息怎样进入本软件？",
])
note(280,151,"对应 2.1（1）（3）",[
    "结构化编组信息订阅、想定与导调兼容",
    "接收时延 ≤50ms（计时边界待确认）",
])
line([(1110,355),(1200,355)],"#c0cddd",2)
arrow([(660,432),(660,505)])
text(681,454,"接入后的编组与事件信息",23,"#627a96")

layer(505,151,"L2","当前状态与变化感知",[
    "整理编组关系、成员类型/数量、能力及执行状态",
    "识别关系、分组与约束的变化",
])
note(505,151,"对应 2.1（2）、2.3（1）",[
    "变化感知；≥4类；1～5台动态增减",
    "新增接入、损毁失联及动态重构要求",
])
line([(1110,580),(1200,580)],"#c0cddd",2)
arrow([(660,657),(660,730)])
text(681,679,"当前状态、条件与规划输入",23,"#627a96")

layer(730,275,"L3","任务规划功能（原图中的决策内核）",[
    "根据输入形成每个平台的任务与时间安排",
],True)
for x,label in ((238,"任务分配与时序"),(524,"优化方向切换"),(810,"能力边界校验")):
    rect(x,856,270,53,"#e1dcfa","#b8ace8",10)
    text(x+16,870,label,24,"#60508f")
text(239,933,"输出：子任务 ／ 任务时序 ／ 时间窗口 ／ 协同约束",26,"#534781")
note(730,162,"对应 2.2（2）、2.3（3）—（5）",[
    "≥5类任务；≥3类优化目标",
    "续航、载荷、传感器、运动性能边界",
    "具体求解方法未由原文指定",
])
rect(1210,918,520,87,"#f0edff","#afa3e4",12)
text(1231,934,"原图候选：MARLlib训练管线",24,"#6551b2")
text(1231,970,"如采用学习策略，提供相应模型参数",21,"#746394")
arrow([(1210,965),(1110,965)],"#9483c6",3)
arrow([(660,1006),(660,1075)])
text(681,1027,"各平台任务与时间安排",23,"#627a96")

layer(1075,155,"L4","下发与执行反馈",[
    "逐平台下发；接收执行状态；判定偏差、失败与超时",
    "异常后的重新分配要求与规划功能衔接",
])
rect(1210,1075,520,155,"#f0eee9","#b7b3aa",14)
text(1234,1098,"单平台智能体（集群 ≥15台）",28,"#5d5b56")
text(1234,1142,"对应 2.2（1）（2）及2.1（4）",23,"#756f65")
text(1234,1180,"双向交互，不等于单向发布消息",23,"#756f65")
arrow([(1110,1120),(1210,1120)],"#708698",3)
text(1120,1088,"任务",20,"#62788e")
arrow([(1210,1190),(1110,1190)],"#708698",3)
text(1120,1202,"反馈",20,"#62788e")

# Feedback is a functional relationship, not a prescribed ROS/deployment wire.
arrow([(210,1150),(105,1150),(105,581),(210,581)],"#5b98a6",4)
text(29,781,"执",24,"#438392")
text(29,818,"行",24,"#438392")
text(29,855,"反",24,"#438392")
text(29,892,"馈",24,"#438392")
text(119,1106,"更新状态",21,"#438392")

rect(210,1270,1520,62,"#edf1f6","#d1dce8",12)
text(232,1289,"跨层验收：整次处理 ≤800ms；动态场景20回合内时序冲突消解率 ≥95%（统计口径待澄清）",25,"#485e77")

rect(210,1380,1520,195,"#e9f5f7","#8dbdc6",16)
rect(234,1400,65,43,"#2a7683","#2a7683",9)
text(245,1407,"L5",25,"#ffffff")
text(318,1404,"仿真、可视化与评估支撑 —— 对应2.4（1）（2）（3）",31,"#286f7b")
text(239,1463,"ROS2桥接Gazebo与UE5 ／ 时间戳对齐（同步误差 ≤50ms）",27,"#326a75")
text(239,1511,"UE5展示编组、子任务与时序 ／ 全链路采集与自动统计",27,"#326a75")
text(211,1349,"L5支撑整条业务链路，不表示只有任务结束后才开始记录或展示。",23,"#5c778a")

text(75,1613,"阅读方式：沿主线看信息如何处理，沿左侧回路看反馈，按右侧编号查条款。",25,"#536b84")
text(75,1660,"五层划分及连线为功能解释，不规定进程或部署；学习工具为原图候选，不代表必选或已验证。",23,"#6b7d92")
text(75,1698,"两个50ms分别指接收时延与时间同步误差；图中门槛均为要求，不是实测结果。",22,"#6b7d92")

svg.append("</svg>")
canvas.save(OUT / "系统功能关系与指标归属.png")
(OUT / "系统功能关系与指标归属.svg").write_text("\n".join(svg),encoding="utf-8")
print("Created functional relationships PNG and SVG")
