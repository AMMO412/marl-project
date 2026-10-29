# -*- coding: utf-8 -*-
"""从已保存的反馈生成离线运动回放；不重跑模拟、不修改原始实验数据。

用法：py -3.14 trajectory_v2.py <run_dir>
HTML/CSS/JS 模板与本文件放在一起，生成的 trajectory.html 无外部依赖。
"""
import html
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from fleet import kind_of, pid_of

KIND_NAME = {"UGV": "轮式车", "TANK": "履带车", "PLANE": "固定翼", "WING": "飞翼"}
KIND_SHAPE = {"UGV": "square", "TANK": "diamond", "PLANE": "triangle", "WING": "cross"}
TYPE_COLOR = {"patrol": "#2563eb", "blockade": "#dc2626", "recon": "#7c3aed",
              "assault": "#ea580c", "hold": "#15803d"}
TYPE_NAME = {"patrol": "巡逻警戒", "blockade": "区域封控", "recon": "协同侦察",
             "assault": "机动突击", "hold": "要点坚守"}
PALETTE = ["#2563eb", "#db2777", "#0d9488", "#d97706", "#7c3aed",
           "#b45309", "#0891b2", "#4f46e5", "#be123c", "#4d7c0f"]
EVENT_NAME = {"job_dispatched": "下发作业", "job_succeeded": "作业完成",
              "job_requeued": "重新排队", "job_failed": "作业失败",
              "member_lost": "平台失联", "timeout": "超时",
              "deviation": "进度偏差", "command_abandoned": "指令终止",
              "behavior_event": "到位行为"}

# 行为层细分事件的中文名（behavior_event 里的 event.kind）
BEHAVIOR_EVENT_NAME = {
    "phase": "行为阶段切换", "checkpoint_visited": "到达检查点",
    "cycle_completed": "完成一圈", "posts_occupied": "封控占位就绪",
    "intrusion_detected": "发现入侵", "interceptor_assigned": "指派拦截",
    "intercepted": "拦截成功", "breach": "越界",
    "map_initialised": "地图初始化", "frontier_mapped": "前沿测绘",
    "coverage_reached": "覆盖达标", "report_sent": "成果回传",
    "map_shared": "共享地图更新", "all_staged": "全员到位",
    "assault_started": "突击开始", "effect_started": "效能施加",
    "effect_applied": "效能达成", "confirmed": "结果确认",
    "on_post": "上岗", "handover_start": "接替开始",
    "handover_complete": "接替完成", "relief": "换班",
    "behavior_complete": "行为完成", "arrived_area": "进入作业区",
    "route_failed": "路径失败", "behavior_sample": "行为轨迹采样",
    "energy_depleted": "电量耗尽", "start_snapped": "出发点吸附",
}


def load_scene_background(scenario, roads_csv=None):
    """场景底图：本地 citysim 道路，或新 SDF 的静态占地；仅作底图，不参与寻路。"""
    meta = scenario.get('_meta', {})
    source = str(meta.get('source', '')) + str(meta.get('source_url', ''))
    empty = dict(roads=[], obstacles=[], label='未提供匹配场景底图')
    if meta.get('sdf'):
        return load_sdf_background(scenario)
    if 'simple_city.world' not in source:
        return empty
    try:
        scale, ox, oy = (float(meta[k]) for k in ('scale', 'offset_x', 'offset_y'))
    except (KeyError, TypeError, ValueError):
        return empty
    if not all(math.isfinite(v) for v in (scale, ox, oy)) or scale <= 0:
        return empty
    # 有源坐标时核对映射，避免将不匹配的背景叠在反馈上。
    for item in scenario.get('platforms', []) + scenario.get('jobs', []):
        raw, pos = item.get('_src_xy_m'), item.get('pos')
        if raw and pos and (abs((raw[0] + ox) * scale - pos[0]) > 0.03
                            or abs((raw[1] + oy) * scale - pos[1]) > 0.03):
            return dict(roads=[], label='场景坐标映射不一致，未叠加底图')
    path = Path(roads_csv) if roads_csv is not None else (
        Path(__file__).resolve().parent.parent / 'outputs' /
        'gazebo_assets_2026-10-26' / 'parsed' / 'roads.csv')
    try:
        content = path.read_bytes()
    except OSError:
        return dict(roads=[], label='本地道路素材缺失，显示坐标网格')
    roads = []
    for row in csv.DictReader(content.decode('utf-8-sig').splitlines()):
        if row['scene'].split(':')[-1] != 'simple_city':
            continue
        pts = json.loads(row['points_xyz_m'])
        roads.append(dict(name=row['name'], width=float(row['width_m']) * scale,
                          points=[[(p[0] + ox) * scale, (p[1] + oy) * scale]
                                  for p in pts]))
    return dict(roads=roads, label='OSRF citysim · simple_city 道路与地标',
                source_file=str(path), source_sha256=hashlib.sha256(content).hexdigest())


def load_sdf_background(scenario):
    """新 SDF 的静态占地底图：与寻路同一套解析，保证图上障碍就是实际障碍。"""
    meta = scenario.get('_meta', {})
    try:
        from city_nav import PROJECT_ROOT, load_sdf_obstacles
        sdf = Path(meta['sdf'])
        if not sdf.is_absolute():
            sdf = PROJECT_ROOT / sdf
        models = meta.get('models')
        geometry = load_sdf_obstacles(
            sdf, bounds=meta.get('bounds'),
            transform=dict(scale=meta.get('scale', 1.0),
                           offset_x=meta.get('offset_x', 0.0),
                           offset_y=meta.get('offset_y', 0.0)),
            models_dir=(PROJECT_ROOT / models if models else None))
    except (OSError, ValueError, KeyError, ImportError) as exc:
        return dict(roads=[], obstacles=[], label='SDF 底图解析失败：%s' % exc)
    obstacles = [dict(polygon=o['polygon'], label=o.get('label') or o['id'],
                      footprint=o.get('footprint'),
                      height_m=(o.get('size_m') or [0, 0, 0])[2])
                 for o in geometry['obstacles']]
    return dict(roads=[], obstacles=obstacles,
                label='container_00_combined_scene.sdf · %d 处静态占地（%d 处取自网格包围盒）'
                      % (len(obstacles),
                         sum(1 for o in obstacles if o['footprint'] == 'mesh_aabb')),
                source_file=str(sdf))


def landmark_label(job):
    """缩短已有地标文字；完整来源文字仍保留在 job 中供悬停查看。"""
    raw = job.get('_src_landmark', '')
    names = {'truss_bridge': '桁架桥', 'radio_tower': '无线电塔',
             'police_station': '警察局', 'osrf_first_office': '办公楼',
             'law_office': '沿街', 'road_x_3': '道路交叉口'}
    return next((name for token, name in names.items() if token in raw), raw[:24])


def _load(run_dir):
    run = Path(run_dir)
    scenario = json.loads((run / "scenario.json").read_text(encoding="utf-8-sig"))
    report = json.loads((run / "report.json").read_text(encoding="utf-8-sig"))
    trace = [json.loads(line) for line in
             (run / "trace.jsonl").read_text(encoding="utf-8-sig").splitlines()
             if line.strip()]
    return scenario, report, trace


def _trajectories(trace):
    """保留旧调用接口：同一平台同一时刻保留最后反馈。"""
    per_worker = defaultdict(dict)
    for r in trace:
        ev = r.get("event") or {}
        if r.get("kind") != "feedback_applied" or not ev.get("worker_id"):
            continue
        pos = ev.get("pos")
        if pos is None or len(pos) < 2:
            continue
        t = float(ev.get("sim_s", r.get("sim_s", 0)))
        per_worker[ev["worker_id"]][t] = (
            t, float(pos[0]), float(pos[1]), float(ev.get("z") or 0),
            float(ev.get("yaw") or 0), ev.get("battery"))
    return {pid: [points[t] for t in sorted(points)]
            for pid, points in per_worker.items()}


def build_replay_data(scenario, report, trace):
    """以场景初始位为起点，最终报告仅补身份，不倒灌最终位置/状态。"""
    final_info = {p["pid"]: p for p in report.get("platforms", [])}
    workers = {}
    for p in scenario.get("platforms", []):
        no = p.get("robot_no")
        pid = p.get("pid") or (pid_of(no) if no is not None else None)
        if pid is None:
            continue
        info = final_info.get(pid, {})
        kind = p.get("kind") or info.get("kind")
        if not kind and no is not None:
            kind = kind_of(no)
        workers[pid] = dict(pid=pid, no=no, kind=kind or "unknown",
                            start=list(p["pos"]), start_z=p.get("z", 0),
                            initial_battery=p.get("battery"), samples=[])
    for row in trace:
        if row.get("kind") != "feedback_applied":
            continue
        ev = row.get("event") or {}
        pid, pos = ev.get("worker_id"), ev.get("pos")
        if not pid or pos is None or len(pos) < 2:
            continue
        if pid not in workers:
            info = final_info.get(pid, {})
            workers[pid] = dict(pid=pid, no=info.get("robot_no"),
                                kind=info.get("kind", "unknown"), start=list(pos),
                                start_z=ev.get("z", 0), initial_battery=None,
                                samples=[], initial_unknown=True)
        workers[pid]["samples"].append(dict(
            t=float(ev.get("sim_s", row.get("sim_s", 0))),
            x=float(pos[0]), y=float(pos[1]), z=float(ev.get("z") or 0),
            yaw=float(ev.get("yaw") or 0), battery=ev.get("battery"),
            job=ev.get("job_id"), status=ev.get("status"), phase=ev.get("phase"),
            command=ev.get("command_id"), progress=ev.get("progress")))
    ordered = []
    for i, pid in enumerate(sorted(workers)):
        worker = workers[pid]
        # dict 的后写覆盖符合 trace 同刻先后顺序。
        dedup = {s["t"]: s for s in worker["samples"]}
        samples = [dedup[t] for t in sorted(dedup)]
        prev = worker["start"]
        distance = 0.0
        for sample in samples:
            distance += math.hypot(sample["x"] - prev[0], sample["y"] - prev[1])
            sample["distance"] = distance
            prev = [sample["x"], sample["y"]]
        worker.update(samples=samples, distance=distance,
                      displacement=math.hypot(prev[0] - worker["start"][0],
                                              prev[1] - worker["start"][1]),
                      color=PALETTE[i % len(PALETTE)],
                      kind_name=KIND_NAME.get(worker["kind"], "未登记类别"),
                      shape=KIND_SHAPE.get(worker["kind"], "square"))
        ordered.append(worker)
    jobs = [dict(j, label=TYPE_NAME.get(j.get("type"), j.get("type", "作业")),
                 landmark=landmark_label(j),
                 color=TYPE_COLOR.get(j.get("type"), "#64748b"))
            for j in scenario.get("jobs", [])]
    events = []
    behaviors = {}      # job_id -> 行为结构（巡逻环/封控岗/侦察区/突击点/坚守岗）
    for r in trace:
        kind = r.get("kind")
        # 行为结构：单独收集，不进入事件列表（供主地图画动作结构）
        if kind == "behavior_event" and (r.get("event") or {}).get("kind") == "behavior_structure":
            ev = r.get("event") or {}
            jid = ev.get("job_id")
            if jid and jid not in behaviors:
                s = dict(ev)
                s.pop("kind", None)
                s["sim_s"] = r.get("sim_s", 0)
                behaviors[jid] = s
            continue
        if kind not in EVENT_NAME:
            continue
        label = EVENT_NAME[kind]
        row = dict(r, label=label)
        # 行为事件：细分 kind 在 event 里，取更具体的中文名，并把 job_id
        # 提升到顶层，供回放事件列表显示作业归属。
        if kind == "behavior_event":
            ev = r.get("event") or {}
            sub = ev.get("kind")
            row["label"] = BEHAVIOR_EVENT_NAME.get(sub, "到位行为")
            if ev.get("job_id") and not row.get("job_id"):
                row["job_id"] = ev["job_id"]
        events.append(row)
    # 包含原始记录顺序；前端稳定排序，同刻末事件生效。
    events.sort(key=lambda e: e.get("sim_s", 0))
    times = [0, report.get("simulated_until_s", 0)]
    times += [s["t"] for w in ordered for s in w["samples"]]
    times += [e.get("sim_s", 0) for e in events]
    return dict(workers=ordered, jobs=jobs, events=events,
                behaviors=[behaviors[j["job_id"]] for j in jobs
                           if j["job_id"] in behaviors],
                end=max(times),
                background=load_scene_background(scenario),
                motion=report.get("motion", "teleport"),
                behavior=report.get("behavior", False),
                run_id=report.get("run_id", ""), meta=scenario.get("_meta", {}))


def build_svg(scenario, report, trace):
    """静态概览接口，供无 JS 预览使用；主页面使用交互回放。"""
    data = build_replay_data(scenario, report, trace)
    positions = [w["start"] for w in data["workers"]]
    positions += [j["pos"] for j in data["jobs"]]
    positions += [[s["x"], s["y"]] for w in data["workers"] for s in w["samples"]]
    positions = positions or [[0, 0], [1, 1]]
    x0 = min(p[0] for p in positions) - 3
    y0 = min(p[1] for p in positions) - 3
    x1 = max(p[0] for p in positions) + 3
    y1 = max(p[1] for p in positions) + 3
    scale = min(960 / (x1 - x0), 590 / (y1 - y0))
    project = lambda p: ((p[0] - x0) * scale + 20, (y1 - p[1]) * scale + 20)
    out = ['<svg viewBox="0 0 1000 650" xmlns="http://www.w3.org/2000/svg">']
    for w in data["workers"]:
        points = [w["start"]] + [[s["x"], s["y"]] for s in w["samples"]]
        out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>'
                   % (" ".join("%.2f,%.2f" % project(p) for p in points), w["color"]))
        x, y = project(points[-1])
        out.append('<text x="%.2f" y="%.2f">%s</text>' % (x, y, html.escape(w["pid"])))
    out.append('</svg>')
    return ''.join(out)


def render(run_dir):
    scenario, report, trace = _load(run_dir)
    data = build_replay_data(scenario, report, trace)
    # 防止输入字段包含 </script> 时提前结束内嵌数据块。
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    template = Path(__file__).with_name('trajectory_player.html').read_text(encoding='utf-8')
    page = template.replace('__RUN_NAME__', html.escape(Path(run_dir).name))
    page = page.replace('__REPLAY_DATA__', payload)
    dst = Path(run_dir) / 'trajectory.html'
    dst.write_text(page, encoding='utf-8')
    return dst


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) != 2:
        sys.exit('用法：py -3.14 trajectory_v2.py <run_dir>')
    print('运动回放：%s' % render(sys.argv[1]))
