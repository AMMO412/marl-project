# -*- coding: utf-8 -*-
"""interop 命令行。

    python -m interop.cli plan --message ... --formation ... --out out/x
    python -m interop.cli compare --suite --out out/compare
    python -m interop.cli to-v2 --message ... --formation ... --out scenario.json
    python -m interop.cli validate --plan out/x/plan.json
    python -m interop.cli sdf --sdf ... --out examples

``plan`` 输出 4.2 的 plan.json / assignments.csv / commands.csv /
report.md / manifest.json。``compare`` 用同一输入跑 unified、基座
planner_v2、M2，输出 compare.json / compare.md。
"""

import argparse
import glob
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import __version__
from .compare import BACKENDS, build_markdown, compare_scenario, summarize
from .errors import UnsupportedFeature, WireError
from .message import load_json, load_scenario, parse_message
from .model import Plan
from .output import write_outputs
from .scheduler import Planner

SUITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios")


def _print_plan_summary(plan: Plan, paths: Dict[str, str]) -> None:
    m = plan.metrics
    print("计划 %s（后端 %s，目标 %s）" % (plan.plan_id, plan.backend,
                                          plan.objective))
    print("  任务 %d，全部落实 %d；槽位 %d，已分配 %d，未分配 %d"
          % (m.tasks_total, m.tasks_fully_assigned,
             m.assigned_subtasks + m.unassigned_subtasks,
             m.assigned_subtasks, m.unassigned_subtasks))
    print("  makespan %.1f s；冲突 %d（已解决 %d）；指令 %d 条；规划 %.0f ms"
          % (m.makespan_s, m.conflicts_detected, m.conflicts_resolved,
             len(plan.commands), m.plan_latency_ms))
    print("  输出：%s" % paths["plan_json"])
    print("  报告：%s" % paths["report_md"])
    print("  清单：%s" % paths["manifest_json"])


def cmd_plan(args) -> int:
    scenario = load_scenario(args.message, args.formation)
    weights = None
    if args.weights:
        parts = [float(x) for x in args.weights.split(",")]
        if len(parts) != 3:
            raise WireError("--weights 需要三个数：time,risk,energy")
        weights = tuple(parts)
    plan = Planner(scenario, objective=args.objective, weights=weights,
                   assignment_mode=args.assignment).plan()
    paths = write_outputs(
        plan, scenario, args.out,
        input_paths=dict(message=args.message, formation=args.formation),
        extra=dict(command=" ".join(sys.argv[1:]),
                   interop_version=__version__))
    _print_plan_summary(plan, paths)
    return 0


def _suite_pairs() -> List[Dict[str, str]]:
    pairs = []
    for message_path in sorted(glob.glob(os.path.join(SUITE_DIR, "*.message.json"))):
        name = os.path.basename(message_path)[:-len(".message.json")]
        formation_path = os.path.join(SUITE_DIR, name + ".formation.json")
        if os.path.exists(formation_path):
            pairs.append(dict(name=name, message=message_path,
                              formation=formation_path))
    return pairs


def cmd_compare(args) -> int:
    objectives = [x.strip() for x in args.objectives.split(",") if x.strip()]
    backends = [x.strip() for x in args.backends.split(",") if x.strip()]
    for backend in backends:
        if backend not in BACKENDS:
            raise WireError("未知后端 %r（可选 %s）" % (backend, "/".join(BACKENDS)))

    if args.suite:
        pairs = _suite_pairs()
    else:
        if not args.message or not args.formation:
            raise WireError("非 --suite 模式需要 --message 与 --formation")
        pairs = [dict(name=os.path.basename(args.message).split(".")[0],
                      message=args.message, formation=args.formation)]
    if not pairs:
        raise WireError("没有找到可对比的样例")

    comparisons = []
    for pair in pairs:
        scenario = load_scenario(pair["message"], pair["formation"])
        comparison = compare_scenario(scenario, objectives=objectives,
                                      backends=backends)
        comparison["name"] = pair["name"]
        comparison["message"] = os.path.abspath(pair["message"])
        comparison["formation"] = os.path.abspath(pair["formation"])
        comparisons.append(comparison)

    os.makedirs(args.out, exist_ok=True)
    payload = dict(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        interop_version=__version__,
        objectives=objectives,
        backends=backends,
        comparisons=comparisons,
        best_by_objective={c["name"]: summarize(c) for c in comparisons},
    )
    json_path = os.path.join(args.out, "compare.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    md_path = os.path.join(args.out, "compare.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(build_markdown(comparisons))
    for comparison in comparisons:
        print("%-20s best=%s" % (comparison["name"],
                                 summarize(comparison)))
    print("对比：%s" % os.path.abspath(md_path))
    print("数据：%s" % os.path.abspath(json_path))
    return 0


def cmd_to_v2(args) -> int:
    """Reject conversion gaps before opening or overwriting any output file."""
    from .conversion_check import v2_conversion_gaps
    scenario = load_scenario(args.message, args.formation)
    gaps = v2_conversion_gaps(scenario)
    if gaps:
        print("拒绝有损转换：%d项缺失能力；未创建或覆盖输出文件。" % len(gaps),
              file=sys.stderr)
        for gap in gaps:
            print("  [%s] %s: %s" % (gap["code"], gap["path"], gap["detail"]),
                  file=sys.stderr)
        return 2
    # A successful branch requires a real lossless adapter, not a renamed scene.
    raise UnsupportedFeature("尚未实现无损v2转换器；未创建或覆盖输出文件")


def cmd_demo(args) -> int:
    """4.1 输入直接驱动基座运行链：interop 规划 + 基座协调/反馈/回放。"""
    from .runtime import InteropPlanner, to_v2_dict
    raw_message = load_json(args.message)
    raw_formation = load_json(args.formation)
    scenario = parse_message(raw_message, raw_formation)
    v2 = to_v2_dict(scenario, raw_message, raw_formation)
    v2["objective"] = ("energy" if args.objective == "energy" else "makespan")
    engine = InteropPlanner(scenario, objective=args.objective, data=v2)
    from run_demo_v2 import simulate
    # T-ASL 的打击与效果判定在基座行为层，运行必须开行为、城市避障和逐步运动；
    # 其余任务沿用命令行参数（--behavior 时用编成表 no_go 约束现造 NavMap）。
    has_asl = any(task.task_type == "T-ASL" for task in scenario.tasks)
    nav = None
    if args.behavior and not has_asl:
        from .runtime import nav_from_scenario
        nav = nav_from_scenario(scenario)
    report, audit = simulate(v2, mode=args.mode, max_ticks=args.max_ticks,
                             motion=("real" if has_asl else args.motion),
                             avoid=(True if has_asl else nav is not None),
                             behavior=(True if has_asl else
                                       (args.behavior and nav is not None)),
                             planner=engine, nav=nav)
    # 同一份 4.1 输入的计划层产物（4.2），与运行报告分开放
    plan = Planner(scenario, objective=args.objective).plan()
    paths = write_outputs(
        plan, scenario, args.out,
        input_paths=dict(message=args.message, formation=args.formation),
        extra=dict(command=" ".join(sys.argv[1:]), planner="interop",
                   runtime_report=os.path.join(os.path.abspath(args.out),
                                               "run", "report.json")))
    _print_plan_summary(plan, paths)

    run_dir = os.path.join(args.out, "run")
    os.makedirs(run_dir, exist_ok=True)
    from reporting_v2 import render_html, render_text
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "trace.jsonl"), "w", encoding="utf-8") as fh:
        for event in audit:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    with open(os.path.join(run_dir, "scenario.json"), "w", encoding="utf-8") as fh:
        json.dump(v2, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "summary.txt"), "w", encoding="utf-8") as fh:
        fh.write(render_text(v2, report, audit, include_events=False))
    with open(os.path.join(run_dir, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(render_html(v2, report, audit))
    try:
        import trajectory_v2
        trajectory_v2.render(run_dir)
    except Exception as exc:   # 回放是附加产物，失败不掩盖主结果
        print("轨迹回放未生成：%s" % exc, file=sys.stderr)

    print("运行：完成 %d/%d，规划事件 %d 条，规划器 %s"
          % (report.get("done", 0), len(report.get("jobs", [])),
             report.get("plans", 0), report.get("planner", "interop")))
    print("运行报告：%s" % os.path.join(run_dir, "report.html"))
    return 0


def cmd_validate(args) -> int:
    from .plan_contract import validate_plan_document
    if not os.path.exists(args.plan):
        raise WireError("计划文件不存在: %s" % args.plan)
    data = load_json(args.plan)
    problems = validate_plan_document(data)
    if problems:
        print("计划校验失败（%d 项）：" % len(problems))
        for problem in problems:
            print("  - %s" % problem)
        return 1
    print("计划校验通过：%d 条分配，%d 条指令"
          % (len(data.get("assignments", [])), len(data.get("commands", []))))
    return 0


def cmd_sdf(args) -> int:
    from . import sdf_scene
    scene = sdf_scene.parse_sdf(args.sdf)
    numbers = [int(x) for x in args.robots.split(",") if x.strip()]
    fleet = sdf_scene.build_fleet(scene, numbers)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "formation.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(fleet, fh, ensure_ascii=False, indent=2)
    print("world=%s bounds=%s boxes=%d robots=%d includes=%d"
          % (scene.world_name, scene.bounds, len(scene.obstacles),
             len(scene.robots), len(scene.includes)))
    print("编成表：%s" % os.path.abspath(path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m interop.cli",
        description="1028 4.1/4.2 统一接口与中性任务规划（融合层）")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="4.1 + 编成表 → 4.2 计划与报表")
    plan.add_argument("--message", required=True)
    plan.add_argument("--formation", required=True)
    plan.add_argument("--out", required=True)
    plan.add_argument("--objective", default="timeliness",
                      choices=("timeliness", "energy", "risk", "balanced"))
    plan.add_argument("--weights", default="", help="time,risk,energy")
    plan.add_argument("--assignment", default="hungarian",
                      choices=("hungarian", "greedy"))
    plan.set_defaults(func=cmd_plan)

    compare = sub.add_parser("compare", help="同输入对比 unified/基座/M2")
    compare.add_argument("--suite", action="store_true", help="跑 interop/scenarios 全部样例")
    compare.add_argument("--message", default="")
    compare.add_argument("--formation", default="")
    compare.add_argument("--out", required=True)
    compare.add_argument("--objectives", default="timeliness,energy")
    compare.add_argument("--backends", default="unified,base_v2,m2")
    compare.set_defaults(func=cmd_compare)

    to_v2 = sub.add_parser("to-v2", help="4.1 输入 → 基座 middle-demo/v2 场景")
    to_v2.add_argument("--message", required=True)
    to_v2.add_argument("--formation", required=True)
    to_v2.add_argument("--out", required=True)
    to_v2.set_defaults(func=cmd_to_v2)

    validate = sub.add_parser("validate", help="校验 4.2 plan.json 的基本契约")
    validate.add_argument("--plan", required=True)
    validate.set_defaults(func=cmd_validate)

    demo = sub.add_parser("demo", help="4.1 输入直接跑基座运行链（interop 规划器）")
    demo.add_argument("--message", required=True)
    demo.add_argument("--formation", required=True)
    demo.add_argument("--out", required=True)
    demo.add_argument("--objective", default="timeliness",
                      choices=("timeliness", "energy", "risk", "balanced"))
    demo.add_argument("--mode", default="normal",
                      choices=("normal", "failure", "timeout", "kill", "deviation"))
    demo.add_argument("--motion", default="teleport",
                      choices=("teleport", "real"))
    demo.add_argument("--max-ticks", type=int, default=200)
    demo.add_argument("--behavior", action="store_true",
                      help="到位后运行基座行为状态机（区域封控的占位/警告/拦阻"
                           "等任务段动作只有开启后才会执行）")
    demo.set_defaults(func=cmd_demo)

    sdf = sub.add_parser("sdf", help="SDF → 编成表骨架")
    sdf.add_argument("--sdf", required=True)
    sdf.add_argument("--robots", default="1,21,31,41")
    sdf.add_argument("--out", required=True)
    sdf.set_defaults(func=cmd_sdf)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (WireError, UnsupportedFeature) as exc:
        print("输入错误：%s" % exc, file=sys.stderr)
        return 2
    except Exception as exc:  # 保留堆栈便于排查，但给出统一前缀
        import traceback
        traceback.print_exc()
        print("运行失败：%s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
