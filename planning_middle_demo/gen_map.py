# -*- coding: utf-8 -*-
"""
gen_map.py —— 把 simple_city 场景 + 初始规划画成一张直观的离线 HTML 地图。

底图 = OSRF citysim simple_city 的真实道路（roads.csv），坐标用原始米坐标
（不是场景缩放坐标），作业点/平台用场景文件里的 _src_xy_m 原值，保证
"图上位置 = 真实世界位置"。航线 = planner_v2.plan(now=0) 的指派结果，
每条线从平台出发位连到作业点，线旁标注出发/开工/完工时刻。

只依赖标准库。用法：
    py -3.14 gen_map.py            # 生成 outputs/simple_city_map.html
"""
import csv
import html
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import planner_v2
from contracts_v2 import build_platforms, build_jobs

PARSED = ROOT.parent / "outputs" / "gazebo_assets_2026-10-26" / "parsed"
ROADS_CSV = PARSED / "roads.csv"

# 五类任务的展示色（与场景 JSON 的 type 对应）
TYPE_COLOR = {
    "patrol":   "#2563eb",  # 蓝  巡逻警戒
    "blockade": "#dc2626",  # 红  区域封控
    "recon":    "#7c3aed",  # 紫  协同侦察
    "assault":  "#ea580c",  # 橙  机动突击
    "hold":     "#15803d",  # 绿  要点坚守
}
TYPE_NAME = {
    "patrol": "巡逻警戒", "blockade": "区域封控", "recon": "协同侦察",
    "assault": "机动突击", "hold": "要点坚守",
}
KIND_SHAPE = {  # 平台类别 -> 标记形状
    "UGV": "square", "TANK": "diamond", "PLANE": "triangle", "WING": "cross",
}
KIND_NAME = {"UGV": "轮式车", "TANK": "履带车", "PLANE": "固定翼", "WING": "飞翼"}


def load_roads():
    """读 simple_city 的道路折线（米坐标）。"""
    roads = []
    with open(ROADS_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not row["scene"].startswith("city:"):
                continue
            pts = json.loads(row["points_xyz_m"])
            roads.append((row["name"], [(p[0], p[1]) for p in pts],
                          float(row["width_m"])))
    return roads


def collect_bounds(roads, pts):
    xs = [x for _, seg, _ in roads for x, _ in seg]
    ys = [y for _, seg, _ in roads for _, y in seg]
    for x, y in pts:
        xs.append(x); ys.append(y)
    pad = 25.0
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def build_svg(w, h, roads, platforms, jobs, assigns):
    """主体 SVG：y 轴翻转（北在上）。"""
    x0, y0, x1, y1 = collect_bounds(roads, [(p["src"][0], p["src"][1]) for p in platforms] +
                                    [(j["src"][0], j["src"][1]) for j in jobs])
    W = 1100
    scale = W / (x1 - x0)
    H = int((y1 - y0) * scale)
    px = lambda x: (x - x0) * scale
    py = lambda y: (y1 - y) * scale          # 翻转 y

    out = []
    out.append('<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
               'style="width:100%%;height:auto;background:#f4f2ec;'
               'font-family:system-ui,sans-serif">' % (W, H))

    # ---- 道路底图 ----
    for name, seg, width in roads:
        d = " ".join("%s,%s" % (px(x), py(y)) for x, y in seg)
        out.append('<polyline points="%s" fill="none" stroke="#d9d4c5" '
                   'stroke-width="%s" stroke-linecap="round"/>' % (d, width * scale))
    for name, seg, _ in roads:
        (ax, ay), (bx, by) = seg[0], seg[-1]
        mx, my = (ax + bx) / 2, (ay + by) / 2
        out.append('<text x="%s" y="%s" font-size="11" fill="#9a9280" '
                   'text-anchor="middle">%s</text>'
                   % (px(mx), py(my) - 4, html.escape(name)))

    # ---- 规划航线（平台出发位 -> 作业点）----
    pid2plat = {p["pid"]: p for p in platforms}
    jid2job = {j["job_id"]: j for j in jobs}
    for a in assigns:
        j = jid2job[a["job_id"]]
        color = TYPE_COLOR.get(j["type"], "#666")
        for pid in a["pids"]:
            p = pid2plat[pid]
            x1s, y1s = px(p["src"][0]), py(p["src"][1])
            x2s, y2s = px(j["src"][0]), py(j["src"][1])
            out.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" '
                       'stroke-width="1.6" stroke-dasharray="7,5" opacity="0.65"/>'
                       % (x1s, y1s, x2s, y2s, color))
            # 线中点小箭头方向示意（三角形）
            ang = math.atan2(y2s - y1s, x2s - x1s)
            mx, my = (x1s + x2s) / 2, (y1s + y2s) / 2
            for dx in (-7, 7):
                tx, ty = mx + dx * math.cos(ang), my + dx * math.sin(ang)
                out.append('<circle cx="%s" cy="%s" r="1.6" fill="%s" opacity="0.65"/>'
                           % (tx, ty, color))

    # ---- 作业点（大圆标 + 类型色）----
    for j in jobs:
        x, y = px(j["src"][0]), py(j["src"][1])
        color = TYPE_COLOR.get(j["type"], "#666")
        tip = "%s %s · %s&#10;地标: %s&#10;原始坐标: (%s, %s) m&#10;高度: %s m · 窗口: [%s, %s] s&#10;需要: %s 台 · 载荷 %s · 传感器 %s&#10;计划: 出发 t=%s 开工 t=%s 完工 t=%s&#10;成员: %s" % (
            j["job_id"], TYPE_NAME.get(j["type"], j["type"]), j["type"],
            j["landmark"], j["src"][0], j["src"][1], j["altitude"],
            j["window"][0], j["window"][1], j["crew"], j["need_payload"],
            j["need_sensor"], a_start(j["job_id"], assigns),
            a_arrive(j["job_id"], assigns), a_end(j["job_id"], assigns),
            "、".join(a_pids(j["job_id"], assigns)))
        out.append('<circle cx="%s" cy="%s" r="13" fill="%s" opacity="0.18"/>'
                   % (x, y, color))
        out.append('<circle cx="%s" cy="%s" r="7" fill="%s" stroke="#fff" '
                   'stroke-width="2"><title>%s</title></circle>'
                   % (x, y, color, tip))
        out.append('<text x="%s" y="%s" font-size="14" font-weight="700" '
                   'fill="%s" text-anchor="middle">%s</text>'
                   % (x, y - 18, color, j["job_id"]))
        out.append('<text x="%s" y="%s" font-size="10" fill="#555" '
                   'text-anchor="middle">%s</text>'
                   % (x, y + 24, html.escape(j["landmark"])))

    # ---- 平台（形状按类别）----
    for p in platforms:
        x, y = px(p["src"][0]), py(p["src"][1])
        kind = p["kind"]
        tip = "%s · %s&#10;出发位: (%s, %s) m&#10;速度 %s · 载荷 %s · 电量 %s&#10;%s" % (
            p["pid"], KIND_NAME.get(kind, kind), p["src"][0], p["src"][1],
            p["speed"], p["payload"], p["battery"],
            ("→ " + "、".join("%s(t=%s)" % (a["job_id"], a["start"])
                              for a in assigns if p["pid"] in a["pids"]) or "初始待命"))
        fill = {"UGV": "#0e7490", "TANK": "#7c2d12", "PLANE": "#4f46e5",
                "WING": "#a16207"}[kind]
        shape = KIND_SHAPE.get(kind, "square")
        if shape == "square":
            body = ('<rect x="-6" y="-6" width="12" height="12" fill="%s" '
                    'stroke="#fff" stroke-width="1.5"/>' % fill)
        elif shape == "diamond":
            body = ('<polygon points="0,-8 8,0 0,8 -8,0" fill="%s" '
                    'stroke="#fff" stroke-width="1.5"/>' % fill)
        elif shape == "triangle":
            body = ('<polygon points="0,-8 7.5,6 -7.5,6" fill="%s" '
                    'stroke="#fff" stroke-width="1.5"/>' % fill)
        else:
            body = ('<g stroke="%s" stroke-width="3.5"><line x1="-7" y1="-7" '
                    'x2="7" y2="7"/><line x1="-7" y1="7" x2="7" y2="-7"/></g>' % fill)
        out.append('<g transform="translate(%s,%s)"><title>%s</title>%s</g>'
                   % (x, y, tip, body))
        out.append('<text x="%s" y="%s" font-size="9" fill="#333" '
                   'text-anchor="middle">%s</text>'
                   % (x, y - 12, p["pid"].replace("rover_", "r")))

    out.append("</svg>")
    return "".join(out)


def _assign(job_id, assigns):
    for a in assigns:
        if a["job_id"] == job_id:
            return a
    return {"pids": [], "start": "?", "end": "?"}

def a_pids(jid, asg): return _assign(jid, asg)["pids"]
def a_start(jid, asg): return _assign(jid, asg)["start"]
def a_arrive(jid, asg):
    a = _assign(jid, asg)
    return a["start"] + a["travel"] if isinstance(a["start"], int) else "?"
def a_end(jid, asg): return _assign(jid, asg)["end"]


def main():
    scenario_path = ROOT / "scenarios" / "simple_city.json"
    sc = json.loads(scenario_path.read_text(encoding="utf-8-sig"))

    platforms = []
    for item, p in zip(sc["platforms"], build_platforms(sc)):
        platforms.append(dict(pid=p.pid, kind=p.kind, src=item["_src_xy_m"],
                              speed=p.speed, payload=p.payload,
                              battery=p.battery))
    jobs = []
    for item, j in zip(sc["jobs"], build_jobs(sc)):
        spec_src = item["_src_xy_m"]
        jobs.append(dict(job_id=j.job_id, type=item["type"], src=spec_src,
                         altitude=item.get("altitude", j.altitude),
                         window=item.get("window", list(j.window)),
                         crew=item.get("crew"), need_payload=j.need_payload,
                         need_sensor=j.need_sensor,
                         landmark=item.get("_src_landmark", "")))

    plats = build_platforms(sc); job_objs = build_jobs(sc)
    plan, _ = planner_v2.plan(plats, job_objs, now=0, H=sc.get("H", 20))
    assigns = [dict(job_id=a.job_id, pids=list(a.pids), start=a.start,
                    travel=a.travel, end=a.end) for a in plan.assignments]

    roads = load_roads()
    svg = build_svg(900, 600, roads, platforms, jobs, assigns)

    legend_jobs = " ".join(
        '<span style="color:%s">●</span> %s' % (c, TYPE_NAME[t])
        for t, c in TYPE_COLOR.items())
    legend_kinds = " ".join(
        '<b style="color:%s">■</b> %s(%s)' % (c, KIND_NAME[k], k)
        for k, c in [("UGV", "#0e7490"), ("TANK", "#7c2d12"),
                     ("PLANE", "#4f46e5"), ("WING", "#a16207")])

    page = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>simple_city 场景与初始规划</title>
<style>
body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:24px;color:#1f2937;background:#faf9f6}
h1{font-size:20px;margin:0 0 4px}
.sub{font-size:12px;color:#6b7280;margin-bottom:14px}
.legend{font-size:13px;margin:10px 0 6px}
.legend+.legend{margin-bottom:14px}
table{border-collapse:collapse;font-size:12.5px;margin-top:18px;width:100%%}
th,td{border:1px solid #d1d5db;padding:5px 9px;text-align:left}
th{background:#eee9dc}
.note{font-size:12px;color:#6b7280;margin-top:14px;line-height:1.7}
</style></head><body>
<h1>OSRF citysim「simple_city」场景 · 6 作业 / 10 平台 · 初始规划航线</h1>
<div class="sub">坐标为真实米坐标（缩放前）· 底图道路取自 simple_city.world · 悬停圆点/图标看详细计划 · 虚线 = 平台出发位 → 作业点</div>
<div class="legend">作业类型：%s</div>
<div class="legend">平台类别：%s　虚线颜色跟随所属作业</div>
%s
<table>
<tr><th>作业</th><th>类型</th><th>真实地标</th><th>坐标 (m)</th><th>成员平台</th><th>出发→开工→完工 (s)</th><th>窗口 (s)</th></tr>
%s
</table>
<div class="note">时间口径：出发 t=now；开工 = 出发 + travel（真实运动含转向与爬升，由
GoalController 预演估算）；完工 = 开工 + 作业时长。图上航线是直线示意，
实际运动层走"先转后走"的闭环轨迹。场景坐标 = 米坐标线性缩放（×0.35），
本图刻意用原始米坐标以对应真实世界。</div>
</body></html>""" % (
        legend_jobs, legend_kinds, svg,
        "".join(
            "<tr><td><b>%s</b></td><td style='color:%s'>%s</td><td>%s</td>"
            "<td>(%s, %s)</td><td>%s</td><td>%s → %s → %s</td><td>[%s, %s]</td></tr>"
            % (j["job_id"], TYPE_COLOR.get(j["type"], "#666"),
               TYPE_NAME.get(j["type"], j["type"]), html.escape(j["landmark"]),
               j["src"][0], j["src"][1],
               "、".join(a_pids(j["job_id"], assigns)),
               a_start(j["job_id"], assigns), a_arrive(j["job_id"], assigns),
               a_end(j["job_id"], assigns), j["window"][0], j["window"][1])
            for j in jobs))

    out = ROOT / "outputs"
    out.mkdir(exist_ok=True)
    dst = out / "simple_city_map.html"
    dst.write_text(page, encoding="utf-8")
    print("已生成:", dst)


if __name__ == "__main__":
    main()
