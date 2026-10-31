# -*- coding: utf-8 -*-
"""运行规划能力版协议沙盒（v2），不导入旧 planning，也不连接真实机器人。

消息骨架沿用 v1（run_id / plan_id / command_id / attempt / 反馈核对 /
取消-确认-重试），在上面装进 planning/ 的六步规则规划器与滚动重规划。

五种演示模式：
  normal     正常：全部作业派完做掉
  failure    第一作业任务级失败一次（触发 exec_fail 重规划 + 重试）
  timeout    第一作业在途停滞（触发超时取消 + 重试）
  kill       中途失联一台平台（触发 member_change 重规划）
  deviation  第一作业进度长期落后（触发 deviation 重规划）

产物目录：outputs/run_YYYYmmdd_HHMMSS_ffffff/（每次新建，禁止覆盖）
  manifest.json / scenario.json / report.json / trace.jsonl /
  summary.txt / report.html
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

from contracts_v2 import (PROTOCOL_V2, check_scenario_v2, resolve_rules,
                          resolve_timeline)
from coordinator_v2 import CoordinatorV2
import fleet
from mock_fleet import MockFleet
from reporting_v2 import render_html, render_text
import trajectory_v2

ROOT = Path(__file__).resolve().parent

MODES = ("normal", "failure", "timeout", "kill", "deviation")


def simulate(scenario, mode="normal", max_ticks=60, max_attempts=2,
             grace_s=1, H=None, K=None, dev_threshold=4.0,
             motion="teleport", avoid=False, behavior=False, planner=None):
    check_scenario_v2(scenario)
    if type(max_ticks) is not int or max_ticks < 1:
        raise ValueError("max_ticks 必须 >= 1")
    if mode not in MODES:
        raise ValueError("未知演示模式：%s" % mode)
    if motion not in ("teleport", "real"):
        raise ValueError("motion 必须是 teleport 或 real")
    # rules 段：可配置参数白名单（dev_threshold/grace_s/max_attempts），
    # 覆盖函数默认值；约束检查仍由代码执行（见 contracts_v2 说明）。
    rules = resolve_rules(scenario)
    if "max_attempts" in rules:
        max_attempts = rules["max_attempts"]
    if "grace_s" in rules:
        grace_s = rules["grace_s"]
    if "dev_threshold" in rules:
        dev_threshold = rules["dev_threshold"]
    # timeline 段：导调事件时间线（已排序、已校验）。member_lost 在
    # 主循环处理（需同时通知 coordinator），作业类事件交给 MockFleet。
    timeline = resolve_timeline(scenario)
    member_lost_events = [e for e in timeline if e["event"] == "member_lost"]
    job_events = [e for e in timeline if e["event"] != "member_lost"]

    # H/K 优先取场景文件里的值（场景作者可为真实地理跨度标定视野），
    # 未在场景里声明时退回默认值。显式传参（如 CLI --H）仍可覆盖。
    if H is None:
        H = scenario.get("H", 20)
    if K is None:
        K = scenario.get("K", 5)
    first_job = scenario["jobs"][0]["job_id"]
    fail_once = {first_job: 2} if mode == "failure" else None
    # timeout：在途延迟到触发超时取消；deviation：对一个协同作业
    # （crew>1）进度打折，让进度落后触发偏差重规划，重规划加人加速
    # 后作业能完成（完整的"检测→重规划→修复"闭环）。
    delay_once = {first_job: 1000} if mode == "timeout" else None
    slow_job, slow_once = None, None
    if mode == "deviation":
        # 挑第一个 crew>1 的作业（协同作业加人才能加速）
        from contracts_v2 import JOB_SPECS
        for item in scenario["jobs"]:
            spec = JOB_SPECS.get(item.get("type"))
            if spec and spec["crew"] > 1:
                slow_job = item["job_id"]
                break
        slow_job = slow_job or first_job
        slow_once = {slow_job: 0.7}
        if dev_threshold == 4.0:
            dev_threshold = 2.0      # 偏差早发现，才有余量加人救回
    # 可选避障：从真实建筑轮廓构造静态障碍图，地面平台按 A* 路径机动。
    nav = None
    if avoid:
        from city_nav import build_nav
        nav, _ = build_nav(scenario)
    # 到位后行为：需要在真实运动 + 静态地图（避障）下才生效。
    behavior = bool(behavior) and motion == "real" and nav is not None
    core = CoordinatorV2(scenario, max_attempts=max_attempts, grace_s=grace_s,
                         H=H, K=K, dev_threshold=dev_threshold, motion=motion,
                         behavior=behavior, planner=planner)
    fleet = MockFleet(fail_once=fail_once, delay_once=delay_once,
                      slow_once=slow_once, motion=motion,
                      timed_events=job_events, nav=nav, behavior=behavior,
                      behavior_params={j["job_id"]: j.get("_behavior", {})
                                       for j in scenario["jobs"]})

    kill_at = None
    kill_pid = None
    if mode == "kill":
        # 挑第一作业计划里的一台成员，在第 8 步失联
        kill_at = 8
        kill_pid = None

    # timeline 的 member_lost 事件：robot_no → pid，在主循环按 t 触发
    lost_events = list(member_lost_events)

    for now in range(max_ticks):
        # 成员损失注入（timeline 数据驱动 + kill 预设模式）
        for e in lost_events:
            if e["t"] != now:
                continue
            pid = fleet_pid_of(e["robot_no"])
            fleet.deactivate(pid)
            core.notify_member_lost(pid, now)
        # 预设 kill 模式：第 8 步挑第一作业成员失联（兼容旧行为）
        if mode == "kill" and kill_pid is None and now >= kill_at:
            for a in (core.plan.assignments if core.plan else []):
                if a.job_id == first_job and a.pids:
                    kill_pid = a.pids[0]
                    break
        if kill_pid is not None:
            fleet.deactivate(kill_pid)
            core.notify_member_lost(kill_pid, now)
            kill_pid = None          # 只注入一次

        for event in fleet.poll(now):
            core.receive(event, now)
        # 到位后行为事件：行为层的 checkpoint_visited/cycle_completed/phase 等
        # 不经过 coordinator 的反馈校验通道，直接作为审计事件追加，
        # 供工作台回放展示"到位后按任务类型行动"的细分阶段。
        for ev in fleet.drain_behavior_events():
            core.audit.append(dict(kind="behavior_event",
                                   sim_s=ev.get("recorded_at_sim_s", now), event=ev))
        commands = core.step(now)
        for event in fleet.submit(commands, now):
            core.receive(event, now)
        if core.report()["settled"]:
            break

    report = core.report()
    report.update(mode=mode, max_ticks=max_ticks, H=H, K=K,
                  dev_threshold=dev_threshold,
                  motion=motion, avoid=bool(avoid), behavior=behavior,
                  behavior_details=any(e.get('kind') == 'behavior_event'
                                       and e.get('event', {}).get('kind') == 'behavior_detail'
                                       for e in core.audit),
                  timeline=[dict(e) for e in timeline],
                  rules=dict(rules),
                  limit_reached=not report["settled"],
                  scope="规则规划 × 消息闭环演示（含成员损失/失败/超时/偏差）")
    return report, core.audit


def fleet_pid_of(robot_no):
    """timeline 里的 robot_no → 本层平台 pid（rover_XX）。"""
    return fleet.pid_of(robot_no)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path,
                        default=ROOT / "scenarios/fleet_demo.json")
    parser.add_argument("--mode", choices=MODES, default="normal")
    parser.add_argument("--max-ticks", type=int, default=60)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--grace-s", type=int, default=1)
    parser.add_argument("--H", type=int, default=None,
                        help="规划视野（步）；默认取场景文件声明，缺省 20")
    parser.add_argument("--K", type=int, default=None,
                        help="滚动重规划周期（步）；默认取场景文件声明，缺省 5")
    parser.add_argument("--dev-threshold", type=float, default=4.0,
                        help="偏差触发阈值（工作量）")
    parser.add_argument("--motion", choices=("teleport", "real"),
                        default="teleport",
                        help="在途语义：teleport=瞬移（规划快进，默认），"
                             "real=真实运动（GoalController 闭环逐步推进）")
    parser.add_argument("--avoid", action="store_true",
                        help="地面平台按真实建筑轮廓做 A* 绕障（需 motion=real）")
    parser.add_argument("--behavior", action="store_true",
                        help="到位后运行行为状态机（巡逻/封控/侦察/突击/坚守），"
                             "需 motion=real 且 --avoid")
    parser.add_argument("--planner", choices=("auto", "base", "interop"),
                        default="auto",
                        help="规划引擎：auto=中性场景用融合统一层、突击场景回退"
                             "基座（默认）；base=基座 planner_v2；interop=强制"
                             "统一层（含突击场景会拒绝）")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--quiet", action="store_true",
                        help="控制台省略逐条事件；完整记录仍保留")
    args = parser.parse_args(argv)
    try:
        content = args.scenario.read_bytes()
        scenario = json.loads(content.decode("utf-8-sig"))
        custom = None
        if args.planner in ("auto", "interop"):
            from interop.errors import UnsupportedFeature, WireError
            from interop.runtime import planner_from_v2
            try:
                custom = planner_from_v2(scenario,
                                         objective=scenario.get("objective"))
            except UnsupportedFeature as exc:
                if args.planner == "interop":
                    parser.exit(2, "该场景不能使用 interop 规划器：%s\n" % exc)
                print("提示：该场景含突击/效果判定，回退基座 planner_v2。",
                      file=sys.stderr)
            except WireError as exc:
                parser.exit(2, "该场景不能使用 interop 规划器：%s\n" % exc)
        report, audit = simulate(scenario, args.mode, args.max_ticks,
                                 args.max_attempts, args.grace_s, args.H,
                                 args.K, args.dev_threshold, args.motion,
                                 args.avoid, args.behavior, planner=custom)
        out = args.out or ROOT / "outputs" / datetime.now().strftime(
            "run_%Y%m%d_%H%M%S_%f")
        # 每次输出独立目录，禁止覆盖已有实验。
        out.mkdir(parents=True, exist_ok=False)
        manifest = dict(protocol=PROTOCOL_V2, python=sys.version,
                        scenario=str(args.scenario.resolve()),
                        scenario_sha256=hashlib.sha256(content).hexdigest(),
                        mode=args.mode, max_ticks=args.max_ticks,
                        max_attempts=args.max_attempts, grace_s=args.grace_s,
                        H=report["H"], K=report["K"],
                        dev_threshold=args.dev_threshold,
                        motion=args.motion, avoid=args.avoid,
                        behavior=args.behavior,
                        planner=report.get("planner", "base_v2"),
                        generated_at=datetime.now().astimezone().isoformat(),
                        backend="mock_only", external_integration_verified=False)
        for name, value in (("manifest.json", manifest),
                            ("scenario.json", scenario),
                            ("report.json", report)):
            (out / name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2),
                encoding="utf-8")
        with (out / "trace.jsonl").open("w", encoding="utf-8") as handle:
            for event in audit:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        (out / "summary.txt").write_text(
            render_text(scenario, report, audit), encoding="utf-8")
        (out / "report.html").write_text(
            render_html(scenario, report, audit), encoding="utf-8")
        # 运动轨迹图：从本次 trace 还原各平台逐拍位姿并可视化
        trajectory_v2.render(str(out))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, "运行失败：%s\n" % error)
    print(render_text(scenario, report, audit, include_events=not args.quiet))
    print("产物：%s" % out.resolve())
    print("可视报告：%s" % (out / "report.html").resolve())
    print("动态运动回放：%s" % (out / "trajectory.html").resolve())
    return 0 if report["all_succeeded"] else 2


if __name__ == "__main__":
    sys.exit(main())
