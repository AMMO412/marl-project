# -*- coding: utf-8 -*-
"""
coordinator_v2.py —— 规划能力版中间层协调器

消息骨架沿用 v1 的纪律：
  * 中间层是运行状态的唯一写入者；一切状态变化都来自被核对过的反馈
  * 指令带 run_id / plan_id / command_id / attempt 身份
  * 反馈核对：协议与运行号 / event_id 去重 / 指令身份一致 /
    时间单调 / 进度单调 / 成功必须有完成证据
  * 超时只请求取消，收到结束反馈才释放平台；失败可重试

在骨架之上装入 planning/ 的规划能力：
  * 六步规划器（planner_v2.plan）产出 H 步内的指派
  * 滚动重规划（K 周期）+ 五类独立触发源
    （init / member_change / exec_fail / timeout / deviation / periodic）
  * 指令只在计划开工步到达、平台空闲、作业待派时下发
    ——同一平台同一时刻只有一个持续指令源（下游发令纪律）
"""
from dataclasses import asdict
from typing import Dict, List, Optional

from contracts_v2 import (PROTOCOL_V2, Command, Job, Platform,
                          delivery_block, task_block)
import planner_v2

TRIGGER_LABELS = {
    "init": "首次规划",
    "member_change": "成员变化",
    "exec_fail": "执行失败",
    "timeout": "超时",
    "deviation": "偏差超阈值",
    "periodic": "滚动周期",
}
_EPS = 1e-6


class CoordinatorV2:
    def __init__(self, scenario, run_id="demo-v2", max_attempts=2,
                 grace_s=1, H=20, K=5, dev_threshold=4.0, motion="teleport",
                 behavior=False, planner=None):
        self.run_id = run_id
        self.max_attempts = max_attempts
        self.grace_s = grace_s
        self.H = H
        self.K = K
        self.dev_threshold = dev_threshold
        self.motion = motion
        self.behavior = bool(behavior)
        # 可插拔规划引擎：None=基座 planner_v2；否则为
        # callable(coord, now) -> (planner_v2.Plan, events)。
        self.custom_planner = planner
        self.planner_name = getattr(planner, "name", "base_v2") if planner else "base_v2"
        self.objective = scenario.get("objective", "makespan")

        from contracts_v2 import build_jobs, build_platforms
        self.platforms = {p.pid: p for p in build_platforms(scenario)}
        self.jobs = {j.job_id: j for j in build_jobs(scenario)}
        # 电量记账基准：一台平台“见过的最大电量”即其满电容量。不能只用
        # 初始化时的 fleet 默认值——上层适配器会把电池抬到很大的值来表示
        # “不对续航做强约束”（见 interop/adapters/base_v2.py），那样报告会
        # 拿 860 去减 600 万，得出百万级负能耗。
        self.energy_capacity = {p.pid: float(p.battery)
                                for p in self.platforms.values()}

        self.active = {}            # command_id -> Command
        self.platform_cmd = {}      # pid -> command_id（单一指令源）
        self.job_cmds = {}          # job_id -> [command_id]
        self.seen = set()
        self.last_fb_time = {}      # command_id -> 最近反馈 sim_s
        self.cmd_progress = {}      # command_id -> 最近进度（工作量）
        self.dispatched = set()     # 已按当前计划下发的 (plan_id, job_id)

        self.plan = None            # 当前计划（planner_v2.Plan）
        self.plan_id = 0
        self.pending = [("init", "首次规划")]
        self.replan_log = []
        self.plan_traces = []
        self.now = -1
        self.audit = []
        self.succeeded_at = {}      # job_id -> 完成步

    # ---------------- 留痕 ----------------
    def record(self, kind, **fields):
        self.audit.append(dict(kind=kind, sim_s=self.now, **fields))

    def advance(self, now):
        if type(now) is not int or now < 0 or now < self.now:
            raise ValueError("演示时间必须是单调不减的非负整数")
        self.now = now

    # ---------------- 上游事件：成员损失 ----------------
    def notify_member_lost(self, pid, now):
        """上层编组通知失联。失联平台不会再有任何反馈，
        其在途指令按「成员变化」路径直接放弃（这是与超时路径的
        显式区别：超时等取消确认，失联不等——没有谁会确认）。"""
        self.advance(now)
        p = self.platforms.get(pid)
        if p is None or not p.alive:
            return False
        p.alive = False
        self.record("member_lost", pid=pid)
        # 放弃该平台在途指令
        cid = self.platform_cmd.get(pid)
        if cid is not None:
            cmd = self.active.pop(cid, None)
            self.platform_cmd.pop(pid, None)
            if cmd is not None:
                self.cmd_progress.pop(cid, None)
                self.record("command_abandoned", command_id=cid,
                            job_id=cmd.job_id, reason="member_lost")
                self._job_after_command_released(cmd)
        self.pending.append(("member_change", "成员损失(%s)" % pid))
        return True

    # ---------------- 反馈消费 ----------------
    def receive(self, event, now):
        """只通过独立消息更新状态；返回是否消费了有效反馈。"""
        self.advance(now)
        if not isinstance(event, dict):
            self.record("feedback_ignored", reason="not_an_object")
            return False

        def ignore(reason):
            self.record("feedback_ignored", reason=reason,
                        event_id=event.get("event_id"))
            return False

        if event.get("protocol") != PROTOCOL_V2 or event.get("run_id") != self.run_id:
            return ignore("protocol_or_run")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            return ignore("missing_event_id")
        if event_id in self.seen:
            return ignore("duplicate")
        command_id = event.get("command_id")
        if not isinstance(command_id, str):
            return ignore("invalid_command_id")
        command = self.active.get(command_id)
        if command is None:
            return ignore("inactive_attempt")
        if (event.get("job_id") != command.job_id
                or event.get("worker_id") != command.worker_id
                or type(event.get("attempt")) is not int
                or event.get("attempt") != command.attempt):
            return ignore("identity_mismatch")
        stamp = event.get("sim_s")
        previous = self.last_fb_time.get(command_id, command.issued_sim_s)
        if type(stamp) is not int or not previous <= stamp <= now:
            return ignore("invalid_or_old_time")
        status = event.get("status")
        if status not in ("accepted", "progress", "succeeded", "failed",
                          "cancelled"):
            return ignore("unknown_status")

        job = self.jobs[command.job_id]
        progress = event.get("progress")
        if type(progress) not in (int, float) or progress < 0:
            return ignore("invalid_progress")
        prev_progress = self.cmd_progress.get(command_id, 0.0)
        if progress < prev_progress - _EPS:
            return ignore("progress_regressed")
        if progress > job.work + _EPS:
            return ignore("progress_overwork")
        if status == "succeeded" and progress < job.work - _EPS:
            return ignore("missing_completion_evidence")

        # 可选位姿/电量字段（消息化的事实，不直接对象引用）
        pos = event.get("pos")
        if pos is not None:
            if (not isinstance(pos, list) or len(pos) != 2
                    or any(type(v) not in (int, float) for v in pos)):
                return ignore("invalid_pos")
            self.platforms[command.worker_id].pos = (float(pos[0]),
                                                     float(pos[1]))
        # 真实运动下反馈携带朝向（yaw），用于 planner 的转向时间估算
        yaw = event.get("yaw")
        if yaw is not None:
            if type(yaw) not in (int, float):
                return ignore("invalid_yaw")
            self.platforms[command.worker_id].yaw = float(yaw)
        battery = event.get("battery")
        if battery is not None:
            if type(battery) not in (int, float) or battery < 0:
                return ignore("invalid_battery")
            platform = self.platforms[command.worker_id]
            platform.battery = float(battery)
            # 容量随读数上抬（适配器接管电量标度时），只增不减。
            self.energy_capacity[platform.pid] = max(
                self.energy_capacity.get(platform.pid, 0.0), float(battery))

        self.seen.add(event_id)
        self.last_fb_time[command_id] = stamp
        self.cmd_progress[command_id] = float(progress)
        if progress > job.progress:
            job.progress = min(float(progress), job.work)
        self.record("feedback_applied", event=dict(event))
        if job.status == "cancelling" and status in ("accepted", "progress"):
            pass                    # 取消在途，忽略中间进度
        elif status == "succeeded":
            if job.status != "succeeded":
                job.status = "succeeded"
                self.succeeded_at[job.job_id] = now
                self.record("job_succeeded", job_id=job.job_id)
            self._release_command(command)
        elif status == "failed":
            self._release_command(command)
            self._job_after_failure(job, now, event.get("note"))
        elif status == "cancelled":
            self._release_command(command)
            self._job_after_command_released(command)
        else:
            if job.status not in ("succeeded", "failed", "cancelling"):
                job.status = "running"
        return True

    # ---------------- 指令生命周期 ----------------
    def _release_command(self, command):
        self.platform_cmd.pop(command.worker_id, None)
        self.active.pop(command.command_id, None)
        self.cmd_progress.pop(command.command_id, None)
        self.record("attempt_finished", job_id=command.job_id,
                    command_id=command.command_id,
                    worker_id=command.worker_id)

    def _job_active_cmds(self, job_id):
        return [c for c in self.active.values() if c.job_id == job_id]

    def _job_after_command_released(self, command):
        """cancelled / 成员放弃路径：本作业还有在途指令则继续等。"""
        job = self.jobs[command.job_id]
        if job.status in ("succeeded", "failed"):
            return
        if self._job_active_cmds(job.job_id):
            return
        # 全部指令已结束
        if job.status == "cancelling":
            if job.attempts < self.max_attempts:
                job.status = "pending"
                self.record("job_requeued", job_id=job.job_id,
                            cause="cancelled", next_attempt=job.attempts + 1)
                # 取消确认后重排：不等 K 周期，否则重试要空等
                self.pending.append(("timeout", "超时取消后重排(%s)" % job.job_id))
            else:
                job.status = "failed"
                self.record("job_failed", job_id=job.job_id,
                            cause="cancelled_attempts_exhausted")

    def _job_after_failure(self, job, now, note):
        """任务级失败：在途指令由下层逐条回 failed，本函数只做作业级处置。"""
        if self._job_active_cmds(job.job_id):
            return                  # 还有成员未回终态，等齐再处置
        if job.status == "succeeded":
            return
        if job.attempts < self.max_attempts:
            job.status = "pending"
            self.record("job_requeued", job_id=job.job_id, cause="failed",
                        next_attempt=job.attempts + 1, note=note)
            self.pending.append(("exec_fail", "执行失败(%s)" % job.job_id))
        else:
            job.status = "failed"
            self.record("job_failed", job_id=job.job_id,
                        cause="failed_attempts_exhausted", note=note)

    # ---------------- 偏差与超时 ----------------
    def _deviation(self, now):
        """执行偏差检测：进度长期落后于"首次下发"时的计划预期则触发重规划。

        基准必须用 job.started_at / job.planned_end（首次下发时固定），
        不能拿当前计划的 a.start——滚动重规划会重置 a.start，
        用它会反复清零期望进度，lag 永远累积不到阈值。
        """
        for job in self.jobs.values():
            if job.status not in ("running", "assigned"):
                continue
            # 行为模式：作业进度由行为状态机（圈数/覆盖率/阶段）决定，
            # 与 work 线性模型不兼容，不做偏差检测（行为层自带兜底）。
            if self.behavior:
                continue
            if job.started_at is None or job.planned_end is None:
                continue
            if not (job.started_at <= now < job.planned_end):
                continue
            span = max(1, job.planned_end - job.started_at)
            expect = job.work * (now - job.started_at) / span
            lag = expect - job.progress
            if lag > self.dev_threshold:
                self.record("deviation", job_id=job.job_id,
                            lag=round(lag, 2))
                self.pending.append(("deviation",
                                     "偏差超阈值(%s,%.1f)" % (job.job_id, lag)))

    def _timeout_cancels(self, now):
        for command in list(self.active.values()):
            job = self.jobs[command.job_id]
            # 行为模式：作业完成由行为状态机判定（自带 max_steps/timeout 兜底），
            # 不因 planner 预估的超时取消——避免巡逻/侦察跑到一半被杀。
            if self.behavior:
                continue
            if (now > command.expected_end_sim_s + self.grace_s
                    and job.status != "cancelling"):
                job.status = "cancelling"
                self.record("timeout", job_id=job.job_id,
                            command_id=command.command_id)

    # ---------------- 规划与下发 ----------------
    def _replan(self, now):
        jobs_visible = [j for j in self.jobs.values()
                        if j.status != "cancelling"]
        if self.custom_planner is not None:
            self.plan, events = self.custom_planner(self, now)
        else:
            self.plan, events = planner_v2.plan(
                list(self.platforms.values()), jobs_visible, now, H=self.H,
                plan_id=self.plan_id, objective=self.objective,
                prev_plan=self.plan, motion=self.motion, behavior=self.behavior)
        self.plan_id += 1
        self.dispatched = set()
        labels = []
        for src, detail in self.pending:
            label = TRIGGER_LABELS.get(src, src)
            self.replan_log.append(dict(at=now, source=src, detail=detail,
                                         plan_id=self.plan.plan_id))
            labels.append("%s:%s" % (label, detail))
        self.plan_traces.append(dict(
            plan_id=self.plan.plan_id, created_at=now,
            rule_version=self.plan.rule_version, objective=self.objective,
            horizon=self.H,
            assignments=[dict(job_id=a.job_id, pids=a.pids, start=a.start,
                              end=a.end, travel=a.travel, dur=a.dur,
                              coord=a.coord)
                         for a in self.plan.assignments],
            rejected=self.plan.rejected,
            triggers=[dict(source=s, detail=d) for s, d in self.pending],
            evidence=events,
        ))
        self.record("plan_emitted", plan_id=self.plan.plan_id,
                    triggers=labels, n_assignments=len(self.plan.assignments),
                    n_rejected=len(self.plan.rejected))
        self.pending = []

    def _dispatch(self, now):
        commands = []
        # 超时取消指令（对全部在途指令逐条发 cancel）。
        # 注意：cancel 指令本身不进 active —— 下层的取消反馈
        # 关联的是**原指令**的 command_id（v1 同款语义）。
        for command in list(self.active.values()):
            job = self.jobs[command.job_id]
            if job.status == "cancelling" and command.action == "start":
                cancel = Command(
                    command_id=command.command_id + ":cancel",
                    job_id=command.job_id, worker_id=command.worker_id,
                    attempt=command.attempt, issued_sim_s=now,
                    start_sim_s=now, expected_end_sim_s=now,
                    action="cancel", target_command_id=command.command_id)
                commands.append(cancel)

        if self.plan is None:
            return commands

        for a in sorted(self.plan.assignments, key=lambda x: (x.start, x.job_id)):
            job = self.jobs.get(a.job_id)
            if job is None or job.status != "pending":
                continue
            key = (self.plan.plan_id, a.job_id)
            if key in self.dispatched:
                continue
            if a.start > now or a.end <= now:
                continue
            # 行为模式：作业时长由行为状态机决定，时间窗只作排程参考，
            # 不在下发前按 deadline 拦截（行为层自带 max_steps/timeout 兜底）。
            if a.end > job.window[1] + _EPS and not self.behavior:
                continue
            pids = [pid for pid in a.pids
                    if self.platforms[pid].alive
                    and pid not in self.platform_cmd]
            if len(pids) < len(a.pids) or len(pids) < job.crew:
                continue            # 有成员忙或失联：本轮不下发，等下次滚动
            job.attempts += 1
            members = list(a.pids)
            for pid in members:
                cmd = Command(
                    command_id="%s:%s:%d:%s" % (self.run_id, job.job_id,
                                                job.attempts, pid),
                    job_id=job.job_id, worker_id=pid, attempt=job.attempts,
                    issued_sim_s=now, start_sim_s=a.start,
                    expected_end_sim_s=a.end,
                    task=task_block(job, members, now),
                    delivery=delivery_block(self.platforms[pid]))
                self.active[cmd.command_id] = cmd
                self.platform_cmd[pid] = cmd.command_id
                commands.append(cmd)
            self.job_cmds[job.job_id] = [c.command_id for c in commands
                                         if c.job_id == job.job_id
                                         and c.attempt == job.attempts]
            self.dispatched.add(key)
            job.status = "assigned"
            # 记录首次下发基准（deviation 检测用，不随重规划漂移）。
            # started_at 必须是"预计开工时刻"（开始贡献进度的时刻），
            # 而不是"下发时刻"：真实运动下要加在途 travel，瞬移下
            # a.start 已含 travel（= 开工时刻）。
            if job.started_at is None:
                if self.motion == "real":
                    job.started_at = now + a.travel
                else:
                    job.started_at = now
                job.planned_end = a.end
            self.record("job_dispatched", job_id=job.job_id,
                        attempt=job.attempts, pids=members,
                        planned_start=a.start, planned_end=a.end)
        return commands

    def step(self, now):
        """一个仿真步：偏差→超时→(按触发)重规划→下发。返回指令消息。"""
        self.advance(now)
        self._deviation(now)
        self._timeout_cancels(now)
        if self.pending:
            self._replan(now)
        commands = self._dispatch(now)
        if commands:
            wire = [c.to_wire(self.run_id, self.plan_id)
                    for c in commands if c.action == "start"]
            wire += [c.to_wire(self.run_id, self.plan_id)
                     for c in commands if c.action == "cancel"]
            return wire
        # 滚动周期：本步结束后 K 步到期，下一步触发重规划
        if (now + 1) % self.K == 0:
            self.pending.append(("periodic", "滚动周期(K=%d)" % self.K))
        return []

    # ---------------- 报告 ----------------
    def settled(self):
        return all(j.status in ("succeeded", "failed")
                   for j in self.jobs.values())

    def report(self):
        jobs = [asdict(j) for j in self.jobs.values()]
        done = [j for j in self.jobs.values() if j.status == "succeeded"]
        # 耗电 = Σ(满电容量 − 当前电量)。用容量基准而不是初始化电量，
        # 适配器中途改写电池标度也不会算出负值。
        used_energy = sum(
            max(0.0, self.energy_capacity.get(p.pid, float(p.battery))
                - float(p.battery))
            for p in self.platforms.values())
        makespan = max(self.succeeded_at.values()) if self.succeeded_at else None
        alive = [p for p in self.platforms.values() if p.alive]
        if len(alive) >= 2:
            cx = sum(p.pos[0] for p in alive) / len(alive)
            cy = sum(p.pos[1] for p in alive) / len(alive)
            spread = sum(((p.pos[0] - cx) ** 2 + (p.pos[1] - cy) ** 2) ** 0.5
                         for p in alive) / len(alive)
        else:
            spread = 0.0
        # need_report 反映"最终仍未解决"的作业：从历史 trace 里收集曾被标
        # need_report 的 job_id，但要剔除后来已经 succeeded 的（历史标记
        # 不因后续成功而撤销，直接沿用会造成"已完成却仍在上报列表"的假象）。
        need_report = sorted({e.get("job_id") for tr in self.plan_traces
                              for e in tr["evidence"] if e.get("need_report")})
        need_report = [jid for jid in need_report
                       if jid not in self.jobs
                       or self.jobs[jid].status != "succeeded"]
        solves = [e for tr in self.plan_traces
                  for e in tr["evidence"] if e.get("kind") == "assign_solve"]
        rej_reasons = {}
        for tr in self.plan_traces:
            for r in tr.get("rejected", []):
                key = r["reason"].split("(")[0]
                rej_reasons[key] = rej_reasons.get(key, 0) + 1
        return dict(
            protocol=PROTOCOL_V2, run_id=self.run_id,
            simulated_until_s=self.now,
            objective=self.objective,
            planner=self.planner_name,
            all_succeeded=all(j.status == "succeeded"
                              for j in self.jobs.values()),
            settled=self.settled(),
            jobs=jobs,
            platforms=[dict(pid=p.pid, kind=p.kind, robot_no=p.robot_no,
                            pos=list(p.pos), battery=round(p.battery, 1),
                            alive=p.alive, topic=p.topic)
                       for p in self.platforms.values()],
            active_commands=len(self.active),
            plans=self.plan_id,
            retries=sum(max(0, j.attempts - 1) for j in self.jobs.values()),
            timeouts=sum(1 for e in self.audit if e["kind"] == "timeout"),
            triggers={s: sum(1 for r in self.replan_log if r["source"] == s)
                      for s in TRIGGER_LABELS},
            done=len(done),
            used_energy=round(used_energy, 1),
            per_task_energy=(round(used_energy / len(done), 2) if done else None),
            makespan=makespan,
            spread=round(spread, 2),
            need_report=need_report,
            solve_summary=dict(
                rounds=len(solves),
                solver=(solves[-1]["solver"] if solves else None),
                optimal=round(sum(e["optimal"] for e in solves), 2),
                greedy=round(sum(e["greedy"] for e in solves), 2),
            ) if solves else None,
            rejected_reasons=rej_reasons,
            limitation=("规则规划消息闭环演示；平台能力参数为我方暂定，"
                        "未连接 ROS/Gazebo 真实执行；指标只用于内部相对比较"),
        )
