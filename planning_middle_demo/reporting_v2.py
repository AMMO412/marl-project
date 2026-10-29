# -*- coding: utf-8 -*-
"""reporting_v2.py —— 规划能力版的文本与 HTML 报告（离线自包含）。"""
import html
import json
from typing import List

from contracts_v2 import JOB_TYPE_LABELS

_JOB_HEADERS = ["作业", "类型", "工作量", "进度", "窗口", "crew",
                "尝试", "状态"]


def _cell(value, width=9):
    text = str(value)
    return text[:width].ljust(width)


def render_text(scenario, report, audit, include_events=True):
    lines = []
    lines.append("== 任务规划中间层 · 规划能力版（%s） ==" % report["protocol"])
    motion_label = {"teleport": "瞬移（规划快进）",
                    "real": "真实运动（GoalController 闭环）"}.get(
        report.get("motion"), report.get("motion", "teleport"))
    lines.append("目标：%s   H=%s   在途语义：%s   仿真推进到 t=%s"
                 % (report["objective"], scenario.get("H", 20),
                    motion_label, report["simulated_until_s"]))
    lines.append("")
    lines.append("作业：共 %d，完成 %d，失败 %d，未结束 %d"
                 % (len(report["jobs"]),
                    sum(1 for j in report["jobs"]
                        if j["status"] == "succeeded"),
                    sum(1 for j in report["jobs"]
                        if j["status"] == "failed"),
                    sum(1 for j in report["jobs"]
                        if j["status"] not in ("succeeded", "failed"))))
    lines.append("规划：共 %d 次；重试 %d 次；超时 %d 次"
                 % (report["plans"], report["retries"], report["timeouts"]))
    lines.append("重规划触发源（各自独立，同一轮可多条）：%s"
                 % {k: v for k, v in report["triggers"].items() if v})
    per = report.get("per_task_energy")
    lines.append("成绩单：总能耗 %.1f，每作业能耗 %s，完成时刻 %s，分散度 %.2f"
                 % (report["used_energy"],
                    "%.2f" % per if per is not None else "无完成作业",
                    report["makespan"] if report["makespan"] is not None
                    else "未完成",
                    report["spread"]))
    lines.append("（比总能耗会被\"干得少\"骗到；完成数不一致时先看完成数）")
    if report.get("rejected_reasons"):
        lines.append("派不出去的原因分布：%s"
                     % report["rejected_reasons"])
    if report.get("need_report"):
        lines.append("需上报上层（本层穷尽手段仍无解）：%s"
                     % report["need_report"])
    if report.get("solve_summary"):
        s = report["solve_summary"]
        lines.append("crew=1 指派求解（%d 轮，%s）：最优合计 %.2f，贪心合计 %.2f"
                     % (s["rounds"], s["solver"], s["optimal"], s["greedy"]))
    lines.append("")
    lines.append(" ".join(_JOB_HEADERS))
    for j in report["jobs"]:
        lines.append(" ".join([
            _cell(j["job_id"], 6), _cell(JOB_TYPE_LABELS.get(j["jtype"],
                                                             j["jtype"]), 10),
            _cell("%.1f" % j["work"]), _cell("%.1f/%.1f"
                                             % (j["progress"], j["work"]), 11),
            _cell("[%d,%d]" % tuple(j["window"]), 11),
            _cell(j["crew"]), _cell(j["attempts"]), _cell(j["status"])]))
    lines.append("")
    lines.append("平台（能力参数为我方暂定，非下游实测）：")
    for p in report["platforms"]:
        lines.append("  %s %s 号%02d  pos(%s,%s) 电量%.1f %s 话题 %s"
                     % (p["pid"], p["kind"], p["robot_no"],
                        p["pos"][0], p["pos"][1], p["battery"],
                        "存活" if p["alive"] else "失联", p["topic"]))
    if include_events:
        lines.append("")
        lines.append("事件（%d 条，完整轨迹见 trace.jsonl）：" % len(audit))
        for e in audit:
            lines.append("  [t=%s] %s %s"
                         % (e.get("sim_s"), e.get("kind"),
                            json.dumps({k: v for k, v in e.items()
                                        if k not in ("sim_s", "kind")},
                                       ensure_ascii=False)))
    lines.append("")
    lines.append("边界：%s" % report["limitation"])
    return "\n".join(lines)


def _js_escape(value):
    return json.dumps(value, ensure_ascii=False)


def render_html(scenario, report, audit):
    jobs_rows = []
    for j in report["jobs"]:
        pct = (100.0 * j["progress"] / j["work"]) if j["work"] else 0.0
        status = j["status"]
        color = {"succeeded": "#1a7f37", "failed": "#b35900",
                 "running": "#0969da", "assigned": "#6e7781",
                 "cancelling": "#9a6700"}.get(status, "#6e7781")
        jobs_rows.append(
            "<tr><td>%s</td><td>%s</td><td>%.1f</td>"
            "<td><div class='bar'><div class='fill' "
            "style='width:%.1f%%'></div></div>%.1f</td>"
            "<td>[%d,%d]</td><td>%d</td><td>%d</td>"
            "<td><span class='tag' style='background:%s'>%s</span></td></tr>"
            % (html.escape(j["job_id"]),
               html.escape(JOB_TYPE_LABELS.get(j["jtype"], j["jtype"])),
               j["work"], pct, j["progress"],
               j["window"][0], j["window"][1], j["crew"], j["attempts"],
               color, html.escape(status)))

    triggers = "".join(
        "<div class='chip'>%s × %d</div>" % (html.escape(k), v)
        for k, v in report["triggers"].items() if v)

    timeline_rows = []
    for e in audit:
        if e.get("kind") in ("plan_emitted", "job_dispatched", "job_succeeded",
                             "job_requeued", "job_failed", "timeout",
                             "member_lost", "deviation", "command_abandoned",
                             "feedback_ignored"):
            detail = html.escape(json.dumps(
                {k: v for k, v in e.items()
                 if k not in ("sim_s", "kind", "event")},
                ensure_ascii=False))
            timeline_rows.append(
                "<tr><td>%s</td><td>%s</td><td class='mono small'>%s</td></tr>"
                % (e.get("sim_s"), html.escape(str(e.get("kind"))), detail))

    per = report.get("per_task_energy")
    cards = """
      <div class='card'><div class='num'>%d/%d</div><div>完成作业</div></div>
      <div class='card'><div class='num'>%d</div><div>规划次数</div></div>
      <div class='card'><div class='num'>%s</div><div>每作业能耗</div></div>
      <div class='card'><div class='num'>%s</div><div>完成时刻</div></div>
      <div class='card'><div class='num'>%.2f</div><div>分散度</div></div>
    """ % (report["done"], len(report["jobs"]), report["plans"],
            "%.2f" % per if per is not None else "—",
            report["makespan"] if report["makespan"] is not None else "—",
            report["spread"])

    need_report = ("".join("<li>%s</li>" % html.escape(j)
                           for j in report["need_report"])
                   or "<li>无</li>")
    rejected = ("".join("<li>%s × %d</li>" % (html.escape(k), v)
                        for k, v in report["rejected_reasons"].items())
                or "<li>无</li>")

    doc = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>规划能力版中间层报告 %s</title>
<style>
body{font-family:"Microsoft YaHei",sans-serif;margin:24px;color:#1f2328;
     background:#fff;max-width:1100px}
h1{font-size:20px}h2{font-size:16px;margin-top:28px}
.cards{display:flex;gap:12px;flex-wrap:wrap}
.card{border:1px solid #d0d7de;border-radius:8px;padding:12px 18px;
      min-width:120px;text-align:center}
.card .num{font-size:22px;font-weight:600}
table{border-collapse:collapse;width:100%%;margin-top:8px;font-size:13px}
th,td{border:1px solid #d0d7de;padding:5px 8px;text-align:left}
th{background:#f6f8fa}
.bar{background:#eef1f4;border-radius:4px;height:10px;width:90px;
     display:inline-block;margin-right:6px;vertical-align:middle}
.fill{background:#0969da;height:10px;border-radius:4px}
.tag{color:#fff;border-radius:10px;padding:1px 8px;font-size:12px}
.chip{display:inline-block;border:1px solid #d0d7de;border-radius:14px;
      padding:2px 10px;margin:2px;font-size:12px}
.mono{font-family:Consolas,monospace}.small{font-size:12px}
.warn{background:#fff8c5;border:1px solid #d4a72c;border-radius:6px;
      padding:10px 14px}
details{margin-top:10px}pre{background:#f6f8fa;padding:10px;
      border-radius:6px;overflow:auto;font-size:12px}
</style></head><body>
<h1>任务规划中间层 · 规划能力版报告</h1>
<p>%s</p>
<p><a href="trajectory.html" style="display:inline-block;background:#2563eb;color:white;
padding:10px 18px;border-radius:8px;text-decoration:none">▶ 打开动态运动回放</a>
<span class="small"> 播放 / 时间轴 / 单台追踪 / 实时位置与路程</span></p>
<div class='cards'>%s</div>
<h2>重规划触发源</h2><div>%s</div>
<h2>作业表</h2>
<table><tr>%s</tr>%s</table>
<h2>需上报上层</h2><ul>%s</ul>
<h2>派不出去的原因</h2><ul>%s</ul>
<h2>事件时间线</h2>
<table><tr><th>t</th><th>事件</th><th>详情</th></tr>%s</table>
<details><summary>本次输入 JSON</summary>
<pre>%s</pre></details>
<p class='warn'>%s</p>
</body></html>""" % (
        html.escape(str(report["run_id"])),
        html.escape("目标 %s · H=%s · 在途语义 %s · 仿真至 t=%s · 重试 %d · 超时 %d"
                    % (report["objective"], scenario.get("H", 20),
                       {"teleport": "瞬移", "real": "真实运动"}.get(
                           report.get("motion"), report.get("motion")),
                       report["simulated_until_s"], report["retries"],
                       report["timeouts"])),
        cards, triggers,
        "".join("<th>%s</th>" % h for h in _JOB_HEADERS),
        "".join(jobs_rows), need_report, rejected,
        "".join(timeline_rows),
        html.escape(json.dumps(scenario, ensure_ascii=False, indent=2)),
        html.escape(report["limitation"]))
    return doc
