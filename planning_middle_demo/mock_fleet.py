# -*- coding: utf-8 -*-
"""
mock_fleet.py —— 模拟下层（独立消息替身）

与 v1 MockPeer 同样的纪律：
  * 只通过 JSON 消息与中间层交互，不持有 Coordinator/Job 引用
  * submit 前强制 JSON 序列化往返，防止对象引用泄漏
  * 取消反馈关联**原指令**的 command_id（取消请求本身不是新作业）

比 v1 多模拟的物理量（均为演示量纲，见 fleet.py）：
  * 在途：两种语义，由 motion 开关决定（见下）
  * 作业：到达后每个成员每步贡献 work_rate，作业级进度为各成员之和
  * 能耗：移动电在到达时一次记清（移动步数×move_cost），
    作业电每步记（work_cost）——与 planner 闸门口径一致
  * 能力闸门（第二道）：目标高度>0 而平台不能爬升 → 拒收并回 failed。
    规划器已有一道闸门；这里是"能力约束必须在下发后也有闸门"的复现。

在途语义（motion 开关，这是本文件与 v1 的关键差异）：
  * motion="teleport"（默认）：瞬移语义，对齐 planning/ 原版 executor
    的"开工即到达"。规划层不需要真实运动就能跑通，作为规划快进。
  * motion="real"：真实运动语义。用 motion.GoalController 闭环，把
    "去作业点"翻译成逐拍 Twist 逐步推进（先转后走、差速不横移、
    飞机才有 linear.z），到位靠容差判定，而不是算步数。这一步
    让中间层产出的指令能真正驱动下游速度级接口，对接那天不废。

噪声注入（演示模式用）：
  fail_once  {job_id: 发令后第几步任务级失败}（仅第一次尝试）
  delay_once {job_id: 在途延迟步数}（仅第一次尝试）
  timed_events  绝对步时间线事件列表（见 contracts_v2.TIMELINE_EVENTS）：
                 poll(now) 在 now == e["t"] 时执行 job_fail / job_delay / job_slow
"""
import json
import math

from behaviors import AreaReconBehavior, ContainmentBehavior
from contracts_v2 import PROTOCOL_V2
import containment_geom as geom
import motion
from vehicle_kinematics import approach, limits_for, turn_toward, turn_radius_for


# 每个规划步内部推进的 Twist 发令拍数（约 20 Hz × 1 步 = 20 拍）。
# 真实运动模式下，一个规划步对应这多次闭环控制迭代。
TWIST_TICKS_PER_STEP = 20


class RelayTarget:
    """一个随仿真时钟推进的目标，封控接管后沿用其处置状态。"""

    def __init__(self, spec):
        self.spec = spec
        self.started_at = None
        self.containment = None
        self.travel_s = math.dist(spec["start"], spec["goal"]) / spec["speed_mps"]

    def position(self, now):
        if self.containment is not None:
            return list(self.containment.pos)
        fraction = min(1.0, max(0.0, now - self.started_at) / self.travel_s)
        return [a + (b - a) * fraction for a, b in zip(self.spec["start"], self.spec["goal"])]


class MockFleet:
    def __init__(self, fail_once=None, delay_once=None, slow_once=None,
                 motion="teleport", timed_events=None, nav=None, behavior=False,
                 behavior_params=None, relay_spec=None, home=None,
                 task_nav=None):
        self.fail_once = dict(fail_once or {})
        self.delay_once = dict(delay_once or {})
        self.slow_once = dict(slow_once or {})   # {job_id: 进度折扣系数}
        # behavior=True 时，平台到位后不"原地刷 work_rate"，而是运行
        # behaviors.py 的对应状态机（巡逻环路/封控拦截/协同侦察/突击四阶段/
        # 坚守轮换），行为目标点经 nav.plan 做 A* 绕障后逐拍闭环跟随。
        # 只有 motion="real" 且有 nav 时才生效（行为层依赖真实位姿推进）。
        self.behavior = bool(behavior)
        # 场景 jobs 里的 _behavior 参数（集结区/侦察/攻击窗口/撤离等），
        # 按 job_id 透传给 behaviors.make_behavior；指令契约本身不带这些
        # 任务级参数，避免把任务模板塞进每台平台的消息里。
        self.behavior_params = {k: dict(v or {})
                                for k, v in (behavior_params or {}).items()}
        self.task_nav = task_nav
        self.relay_target = RelayTarget(relay_spec) if relay_spec else None
        self.home = dict(home or {})
        self.return_state = {}
        # 绝对步时间线事件：已按 t 升序；同一步多事件全部处理，不吞。
        # member_lost 不在本层处理（见 _apply_timed_events）。
        self.timed_events = sorted(timed_events or [], key=lambda e: e["t"])
        self._timed_idx = 0
        self._pending_job_events = []   # 已到期但目标作业尚未在途，等待触发
        if motion not in ("teleport", "real"):
            raise ValueError("motion 必须是 teleport 或 real")
        self.motion = motion
        # 可选：静态障碍地图（city_nav.NavMap）。给出后，地面平台在
        # motion="real" 下按 A* 路径逐点跟随，而不是直线奔向目标。
        self.nav = nav
        self.commands = {}        # command_id -> wire（含缓存回执）
        self.replies = {}         # command_id -> [event]（幂等重发）
        self.jobs = {}            # job_id -> dict(members, progress, ...)
        self.platforms = {}       # pid -> dict(pos, battery, active, dead, ...)
        self.counter = 0
        # 行为模式：到位后行为层产生的细分事件（供回放展示），
        # 由 simulate 层 drain 进审计，不进 coordinator 反馈校验通道。
        self.motion_recorder = None
        self.motion_offsets = {}
        self.behavior_events = []

    # ---------------- 工具 ----------------
    @staticmethod
    def _pose(st):
        return (*st['pos'], st['z'], st['yaw'])


    def _event(self, wire, now, status, progress, phase=None, note=None,
               subtask_progress=None):
        self.counter += 1
        command = wire["command"]
        pid = command["worker_id"]
        st = self.platforms.get(pid, {})
        ev = dict(protocol=PROTOCOL_V2, run_id=wire["run_id"],
                  event_id="fleet:%d" % self.counter,
                  command_id=command["command_id"],
                  job_id=command["job_id"], worker_id=pid,
                  attempt=command["attempt"], sim_s=now, status=status,
                  progress=round(float(progress), 4),
                  phase=phase,
                  pos=[round(st.get("pos", (0.0, 0.0))[0], 3),
                       round(st.get("pos", (0.0, 0.0))[1], 3)],
                  battery=round(st.get("battery", 0.0), 2),
                  ammo=int(st.get("ammo", 0)),
                  note=note)
        if subtask_progress is not None:
            ev["subtask_progress"] = round(max(0.0, min(1.0, float(subtask_progress))), 4)
        # 真实运动模式下附加高度/航向（coordinator 对未知字段忽略，安全）
        if self.motion == "real":
            ev["z"] = round(st.get("z", 0.0), 3)
            ev["yaw"] = round(st.get("yaw", 0.0), 4)
        return ev

    def _platform_state(self, wire):
        """以 worker_id(pid) 为 key，与 _event / poll 的读取口径一致。"""
        command = wire["command"]
        delivery = command["delivery"]
        pid = command["worker_id"]
        return self.platforms.setdefault(
            pid, dict(pos=tuple(delivery["pos"]),
                      yaw=0.0, z=0.0,
                      battery=float(delivery["battery"]),
                      ammo=int(delivery.get("ammo", 0) or 0),
                      active=False, dead=False))

    def deactivate(self, pid):
        """模拟平台失联（成员损失）：不再贡献进度、不再回任何反馈。

        若该平台正在执行带行为状态机的作业，同时通知行为层记"我方损失"，
        否则行为层会继续把失联平台算在位/可开火，辅助指标就对不上事实。
        """
        st = self.platforms.get(pid)
        if st is not None:
            st["dead"] = True
            st["active"] = False
        if (st and st.get("return_profile") and pid in self.home
                and self.return_state.get(pid, {}).get("status") != "returned"):
            self.return_state.setdefault(pid, dict(home=list(self.home[pid])))["status"] = "lost"
        for job in self.jobs.values():
            runner = job.get("bh_runner")
            if runner is None:
                continue
            if pid in runner.agents:
                runner.behavior.report_loss(pid, runner.time)

    # ---------------- 绝对步时间线事件 ----------------
    def _apply_timed_events(self, now, events):
        """执行 now 命中的 job 类事件（job_fail / job_delay / job_slow）。

        member_lost 不在本方法处理：它需要同时通知 coordinator
        （fleet.deactivate + core.notify_member_lost），由 simulate 层执行。

        语义：job 类事件的 t 是绝对仿真步。第 t 步时若目标作业已在途则
        触发；若尚未在途（作业还没下发），事件进入 pending，等作业在途后
        立即触发——"让作业失败"必须等作业先开始，不能因为 t 设早了而
        静默丢失。
        """
        # 先把"到期"的事件从主队列移入待处理
        while self._timed_idx < len(self.timed_events):
            e = self.timed_events[self._timed_idx]
            if e["t"] > now:
                break
            self._timed_idx += 1
            self._pending_job_events.append(e)
        # 处理待触发事件：作业在途则触发，否则继续等
        still_pending = []
        for e in self._pending_job_events:
            job = self.jobs.get(e["job_id"])
            if job is None:
                still_pending.append(e)     # 作业尚未在途，继续等
                continue
            kind = e["event"]
            if kind in ("job_fail", "job_timeout"):
                for key, m in list(job["members"].items()):
                    st = self.platforms.get(
                        m["wire"]["command"]["worker_id"])
                    if st is not None:
                        st["active"] = False
                    events.append(self._event(
                        m["wire"], now, "failed", job["progress"],
                        note="timeline 注入的任务级失败"))
                self.jobs.pop(e["job_id"], None)
            elif kind == "job_delay":
                for m in job["members"].values():
                    m["arrival"] += e["delay"]   # 顺延在途到达时刻
            elif kind == "job_slow":
                self.slow_once[e["job_id"]] = e["factor"]   # 后续推进打折
        self._pending_job_events = still_pending

    # ---------------- 指令接收 ----------------
    def submit(self, messages, now):
        events = []
        for wire in json.loads(json.dumps(messages)):
            if wire.get("protocol") != PROTOCOL_V2:
                raise ValueError("模拟下层协议版本不匹配")
            command = wire["command"]
            key = command["command_id"]
            if key in self.replies:
                events.extend(json.loads(json.dumps(self.replies[key])))
                continue
            replies = []
            if command["action"] == "cancel":
                original = self.commands.get(command["target_command_id"])
                job = self.jobs.get(command["job_id"])
                if original is not None and job is not None:
                    members = job["members"]
                    target_key = command["target_command_id"]
                    item = members.pop(target_key, None)
                    if item is not None:
                        st = self.platforms.get(
                            original["command"]["worker_id"])
                        if st is not None:
                            st["active"] = False   # 显式停止后平台空闲
                        replies.append(self._event(
                            original, now, "cancelled", job["progress"]))
                        if not members:
                            del self.jobs[command["job_id"]]
            elif command["action"] == "start":
                delivery = command["delivery"]
                task = command["task"]
                st = self._platform_state(wire)
                if st["active"]:
                    raise ValueError("模拟下层拒绝同一平台同时执行两个作业")
                # 第二道能力闸门：地面平台接不到有高度的作业
                if task["altitude"] > 0 and not delivery["can_climb"]:
                    replies.append(self._event(
                        wire, now, "failed", 0.0,
                        note="目标高度%.0f超出平台能力（无 linear.z）"
                             % task["altitude"]))
                else:
                    previous_return = self.return_state.pop(command["worker_id"], None)
                    if previous_return and previous_return["status"] == "returning":
                        self.behavior_events.append(dict(kind="return_interrupted",
                            pid=command["worker_id"], recorded_at_sim_s=now))
                    st["active"] = True
                    st.pop("_return_nav", None)
                    st["return_profile"] = {
                        k: delivery[k]
                        for k in ("can_climb", "speed", "move_cost")}
                    st["return_profile"]["kind"] = delivery.get("kind")
                    st["return_profile"]["orbit_radius"] = (
                        delivery.get("motion", {}).get(
                            "min_turn_radius_m"))
                    st["return_profile"]["orbit_yaw_rate"] = (
                        delivery.get("motion", {}).get(
                            "max_yaw_rate_rad_s", 0.35))
                    start = st["pos"]
                    delay = 0
                    if command["attempt"] == 1:
                        delay = self.delay_once.get(command["job_id"], 0)
                    job = self.jobs.setdefault(command["job_id"], dict(
                        work=float(task["work"]),
                        progress=0.0, members={}))
                    if self._behavior_on(command["job_id"]):
                        # 行为模式：到位后启动行为状态机，job 级协同推进
                        job.setdefault("bh_runner", None)
                        job.setdefault("bh_job", None)
                        job.setdefault("bh_started", False)
                    target = (task["position"][0], task["position"][1])
                    goal = task.get("goal") or dict(
                        x=target[0], y=target[1],
                        z=task.get("altitude", 0.0), yaw=0.0)
                    # 瞬移语义（对齐 planning/ 原版 executor）：到开工时刻
                    # （start_sim_s）即视为已到达作业点，不逐步模拟在途。
                    # travel 只用于开工时一次记清移动电。
                    travel = max(1, int(math.ceil(
                        math.hypot(target[0] - start[0],
                                   target[1] - start[1])
                        / max(delivery["speed"], 1e-6))))
                    member = dict(
                        wire=wire, start_pos=start, target=target,
                        goal=goal,
                        arrival=command["start_sim_s"] + delay,
                        travel_steps=travel,
                        charged=False, last_phase=None, last_progress=None,
                         share=task.get('subtask_share'), contributed=0.0)
                    # 行为模式下位移全部由行为层推进（含机动集结），替身不再
                    # 另算一条"去作业点"的路：那条路不会被执行，却会出现在
                    # 轨迹与路由统计里，等于虚报一段行程。
                    if (self.motion == "real"
                            and not self._behavior_on(command["job_id"])):
                        # 真实运动：初始化闭环控制器，逐步推进到 goal
                        caps = delivery.get("motion_caps") or {}
                        if (self.nav is not None
                                and not bool(delivery.get("can_climb"))):
                            # 地面平台走 A* 绕障路径；空中平台越障直飞
                            st_pos = st["pos"]
                            try:
                                scoped_router = getattr(
                                    self.nav, "route_router", None)
                                if (getattr(self.nav, "prefer_scoped_router",
                                            False)
                                        and scoped_router is not None):
                                    route = scoped_router.route(
                                        st_pos, target, is_air=False)
                                    plan = dict(
                                        path=[list(point)
                                              for point in route.path],
                                        length=route.length_m,
                                        straight_length=math.dist(
                                            st_pos, target),
                                        straight_line_ok=(
                                            len(route.path) == 2),
                                        min_clearance=(
                                            scoped_router.margin_m),
                                        expanded=0,
                                        source="scoped_city_route",
                                    )
                                else:
                                    if not self.nav.free(st_pos):
                                        st_pos, _ = self.nav.nearest_free(
                                            st_pos, max_radius=6.0)
                                        st["pos"] = st_pos
                                    goal_xy, _ = self.nav.nearest_free(
                                        target, max_radius=8.0)
                                    plan = self.nav.plan(st_pos, goal_xy, corner_radius=turn_radius_for(
                                        delivery.get('kind') or 'UGV', delivery['speed']))
                            except Exception as exc:      # noqa: BLE001
                                replies.append(self._event(
                                    wire, now, "failed", 0.0,
                                    note="避障路径不可达：%s" % exc))
                                self.jobs.pop(command["job_id"], None)
                                continue
                            # Densification is for drawing, not a sequence of
                            # separate stops. Keep corners, drop collinear points.
                            compact = []
                            for point in plan["path"]:
                                while len(compact) >= 2:
                                    a, b = compact[-2:]
                                    ux, uy = b[0] - a[0], b[1] - a[1]
                                    vx, vy = point[0] - b[0], point[1] - b[1]
                                    if (abs(ux * vy - uy * vx) > 1e-8
                                            or ux * vx + uy * vy < 0):
                                        break
                                    compact.pop()
                                compact.append(point)
                            member["route"] = compact
                            member["route_i"] = 1
                            member["route_meta"] = plan
                            self.behavior_events.append(dict(
                                kind="approach_route", job_id=command["job_id"],
                                recorded_at_sim_s=now,
                                route=dict(pid=command["worker_id"],
                                           job_id=command["job_id"],
                                           recorded_at_sim_s=now,
                                           from_pose=list(st_pos), to=list(goal_xy),
                                           path=[list(p) for p in plan["path"]],
                                           length=plan["length"],
                                           straight=plan["straight_length"],
                                           straight_line_ok=plan["straight_line_ok"],
                                           min_clearance=plan["min_clearance"],
                                           source=plan.get(
                                               "source", "approach_astar"))))
                            goal = dict(x=plan["path"][-1][0],
                                        y=plan["path"][-1][1],
                                        z=0.0, yaw=0.0)
                            member["goal"] = goal
                        limits = limits_for(delivery.get('kind') or 'UGV', delivery['speed'])
                        gains = motion.DriveGains(
                            max_linear_accel=limits.max_accel,
                            max_linear_decel=limits.max_decel,
                            max_angular_accel=limits.max_yaw_accel,
                            max_lateral_accel=limits.max_lateral_accel,
                            max_linear=float(caps.get("max_linear",
                                                     delivery["speed"])),
                            max_angular=float(caps.get("max_angular", 0.5)),
                            tol_pos=float(caps.get("tol_pos", 0.5)),
                            tol_yaw=float(caps.get("tol_yaw", 0.15)))
                        member["ctl"] = motion.GoalController(
                            gains, can_climb=bool(delivery.get("can_climb")))
                    job["members"][key] = member
                    replace_pid = task.get("replace_pid")
                    if (replace_pid and job.get("bh_runner") is not None
                            and hasattr(job["bh_runner"], "replace_agent")):
                        cap = dict(kind=delivery.get("kind"),
                                   can_climb=bool(delivery.get("can_climb")),
                                   start_z=float(st.get("z") or 0.0),
                                   air_v=st.get('_air_v', 0.0), air_w=st.get('_air_w', 0.0),
                                   ground_v=st.get('_ground_v', 0.0), ground_w=st.get('_ground_w', 0.0),
                                   payload=delivery.get("payload"),
                                   sensor=delivery.get("sensor"),
                                   speed=float(delivery.get("speed") or 0.8))
                        job["bh_runner"].replace_agent(
                            replace_pid, command["worker_id"], (*st["pos"], st["yaw"]),
                            float(delivery.get("speed") or 0.8), cap)
                        job.setdefault("bh_odo", {})[command["worker_id"]] = 0.0
                        job["bh_odo"].pop(replace_pid, None)
                        behavior = job["bh_runner"].behavior
                        if behavior.kind == 'patrol':
                            self.behavior_events.append(dict(
                                kind="behavior_structure", **self._behavior_structure(behavior)))
                    self.commands[key] = wire
                    replies.append(self._event(wire, now, "accepted", 0.0,
                                               phase="travel"))
            else:
                raise ValueError("未知指令")
            self.replies[key] = replies
            events.extend(replies)
        return events

    # ---------------- 行为层（behavior 模式） ----------------
    def _behavior_on(self, job_id=None):
        """行为层只在真实运动 + 有静态地图时启用。"""
        params = self.behavior_params.get(job_id, {})
        configured = (params.get("_workbench_task")
                      or params.get("_workbench_patrol"))
        return (self.motion == "real" and not params.get("movement_only")
                and ((self.behavior and self.nav is not None)
                     or (configured and self.task_nav is not None)))

    def _behavior_job_dict(self, job):
        """从 member 的 task 提取行为层要用的 job dict（type/pos/job_id）。

        行为层（behaviors.make_behavior）读 job.get('type')；指令 task 里存
        的是 jtype（task_block 用 jtype=job.jtype，simple_city 下即五类 type）。
        """
        m = next(iter(job["members"].values()))
        task = m["wire"]["command"]["task"]
        out = dict(job_id=task["job_id"], type=task["jtype"],
                   pos=[task["position"][0], task["position"][1]],
                   # 当前执行版本：评估结果绑定 attempt，重试即新版本
                   attempt=m["wire"]["command"].get("attempt", 1))
        params = dict(self.behavior_params.get(task["job_id"]) or {})
        # 融合层计划下发的角色（边界段/门哨/机动组）随指令到达；基座原生
        # 场景没有 roles 字段，行为层按几何自行分工。
        roles = task.get("roles") or {}
        if roles:
            params["roles"] = dict(roles)
        if roles and params.get("search_points_by_role"):
            points = params["search_points_by_role"]
            params["search_starts"] = {
                pid: points[role]
                for pid, role in roles.items() if role in points}
        # The dispatched plan is authoritative for role placement. Random task
        # relocation can replace the template's default scout/assessor with
        # other platforms, so stale scout_pid/assessor_pid values from the
        # scenario must not leak into an attempt that carries explicit roles.
        if task["jtype"] == "assault" and roles:
            for role in ("scout", "assessor"):
                params[role + "_pid"] = next(
                    (pid for pid, assigned in roles.items()
                     if assigned == role), None)
        # 融合层计划路线（unit_id → path）转成行为层 pid → path。
        # 只对带路线数据的任务透传，避免旧场景/基座行为收到空字段。
        planned_paths = getattr(job, "_interop_paths", None)
        if not planned_paths and isinstance(job, dict):
            planned_paths = job.get("_interop_paths")
        if planned_paths:
            params["_planned_assignments"] = [
                {"unit_id": pid, "path": [list(point) for point in path]}
                for pid, path in planned_paths.items()
            ]
        if params:
            out["_behavior"] = dict(params)
        return out

    def _ensure_behavior(self, job, now):
        """作业一在途就交给行为状态机，返回 BehaviorRunner 或 None。

        T-ASL 的"机动"是任务的一部分：平台从受领任务的位置出发，自己开到
        集结区/观察位。若等替身先把全员挪到集结位再启动行为，机动段就不在
        行为时钟里，`all_staged` 会落在 t=0（看起来像瞬移）。因此这里从下发
        时刻就建 runner，由行为层自己规划集结路径，替身不再另走一套在途。
        """
        runner = job.get("bh_runner")
        if runner is not None:
            return runner
        members = job["members"]
        if not members:
            return None
        task = next(iter(members.values()))["wire"]["command"]["task"]
        job_id = task["job_id"]
        if not self._behavior_on(job_id):
            return None
        from behaviors import make_behavior
        from behavior_runtime import BehaviorRunner
        bh_job = self._behavior_job_dict(job)
        relay = self.relay_target
        if relay and bh_job["job_id"] == relay.spec["source_job_id"] and relay.started_at is None:
            relay.started_at = now - 1
        if relay and relay.started_at is not None:
            bh_job["_relay_target"] = relay
            bh_job["_relay_origin_s"] = now - 1
        params = bh_job.get("_behavior") or {}
        if bh_job["type"] == "hold" and params.get("positions"):
            params["task_limit_s"] = max(0, task["window"][1] - now)
        if params.get("target_start_mode") == "after_control":
            params["max_steps"] = max(
                0, min(params.get("max_steps", 600),
                       task["window"][1] - now - 1))
        if bh_job["type"] == "recon" and "search_deadline_s" in params:
            remaining = max(0, params["search_deadline_s"] - now)
            params["search_limit_s"] = min(
                params.get("search_limit_s", remaining), remaining)
        pids = [m["wire"]["command"]["worker_id"]
                for m in members.values()]
        if (bh_job["type"] == "recon"
                and params.get("area")
                and not params.get("search_starts")):
            # 四点区域是执行契约本身，不要求场景额外重复写
            # search_starts。没有显式扇区时，以实际派发瞬间的位姿作为
            # 扇区中心；AreaReconBehavior 会立即把这些起点替换为区内
            # 未知网格并持续补盲。
            starts_hint = {}
            for pid in pids:
                platform = self.platforms.get(pid) or {}
                pos = platform.get("pos", (0.0, 0.0))
                starts_hint[pid] = (float(pos[0]), float(pos[1]))
            if starts_hint:
                params["search_starts"] = starts_hint
        configured = (params.get("_workbench_task")
                      or params.get("_workbench_patrol"))
        nav = self.task_nav() if configured and self.task_nav else self.nav
        behavior = make_behavior(bh_job, nav, pids)
        starts = {}
        speeds = {}
        caps = {}
        for m in members.values():
            pid = m["wire"]["command"]["worker_id"]
            st = self.platforms.get(pid, {})
            pos = st.get("pos", (0.0, 0.0))
            starts[pid] = (pos[0], pos[1], st.get("yaw", 0.0))
            delivery = m["wire"]["command"]["delivery"]
            speed_caps = delivery.get("motion_caps") or {}
            speeds[pid] = float(speed_caps.get("max_linear", 0.8))
            # 平台画像：地面/空中分流、初始高度、载荷。行为层据此决定
            # 绕障还是直飞、爬升到多少，以及"突击组载荷是否达标"的第二道闸门。
            caps[pid] = dict(kind=delivery.get("kind"),
                             can_climb=bool(delivery.get("can_climb")),
                             start_z=float(st.get("z") or 0.0),
                             payload=delivery.get("payload"),
                             sensor=delivery.get("sensor"),
                             speed=float(delivery.get("speed") or speeds[pid]),
                             heading_initialized=bool(
                                 st.get("_heading_initialized", False)))
        job["bh_job"] = bh_job
        job["bh_runner"] = BehaviorRunner(
            nav, behavior, starts, speeds=speeds, caps=caps,
            air_nav=getattr(nav, "air_threat_nav", None))
        # A platform keeps the heading it ended the previous task with.  The
        # one-time launch alignment is therefore only valid for its first
        # behaviour runner, not when the same aircraft is reassigned later.
        for pid, cap in caps.items():
            if cap.get("can_climb"):
                self.platforms.setdefault(pid, {})[
                    "_heading_initialized"] = True
        job["bh_started"] = True
        job["bh_origin_s"] = now - 1
        job["bh_seen_events"] = 0
        job["bh_seen_routes"] = 0
        job["bh_seen_samples"] = 0
        if hasattr(behavior, "set_platform_caps"):
            behavior.set_platform_caps(caps)
        # 平台级弹药基数注入（编成参数 PLANNING_PARAMS.ammo → delivery）：
        # 行为层的齐射消耗以平台实际弹药为准；无弹药数据的旧指令保持
        # 行为默认（ammo_per_platform），不强行清零。
        if hasattr(behavior, "set_platform_ammo"):
            ammo_map = {pid: int(self.platforms.get(pid, {}).get("ammo") or 0)
                        for pid in pids}
            if any(v > 0 for v in ammo_map.values()):
                behavior.set_platform_ammo(ammo_map)
        # 里程出账基线：行为层接管全部位移后，能耗按实际行程累计
        job["bh_odo"] = {pid: 0.0 for pid in pids}
        # 行为启动时把"结构几何"带出（巡逻环/封控岗/侦察区/突击点/坚守岗），
        # 供回放在主地图上画出五类任务的动作结构（不只画轨迹线）。
        self.behavior_events.append(
            dict(kind="behavior_structure", **self._behavior_structure(behavior)))
        return job["bh_runner"]

    def _behavior_structure(self, behavior):
        """提取行为层的静态结构几何（不随步变化的环/岗/区/点），供可视化。"""
        r = dict(job_id=behavior.job_id, type=behavior.kind,
                 site=[round(v, 2) for v in behavior.site])
        try:
            if behavior.kind == 'patrol':
                r['loop'] = [[round(p[0], 2), round(p[1], 2)]
                             for p in behavior.loop]
                if behavior.sensor_radii:
                    r['sensor_radii'] = dict(behavior.sensor_radii)
                    r['air_pids'] = list(behavior.patrol_groups['air'])
                    r['cell_size_m'] = behavior.cell_size_m
                if behavior.params.get('observation_target'):
                    r['observation_target'] = json.loads(json.dumps(
                        behavior.params['observation_target']))
                air_patrol = behavior.metrics.get('air_patrol') or {}
                if air_patrol:
                    r['air_patrol'] = json.loads(json.dumps(air_patrol))
                    r['air_routes'] = {
                        pid: [[round(point[0], 2), round(point[1], 2)]
                              for point in route]
                        for pid, route in behavior.air_routes.items()
                    }
            elif behavior.kind == 'blockade':
                if getattr(behavior, 'polygon', None):
                    # 1028 区域封控：真实边界 + 分段占位 + 门哨 + 机动组
                    r['area'] = [[round(p[0], 2), round(p[1], 2)]
                                 for p in behavior.polygon]
                    r['posts'] = [list(post['point']) for post in behavior.post_list]
                    r['post_plan'] = [dict(post) for post in behavior.post_list]
                    r['gates'] = [dict(gate) for gate in behavior.gates]
                    r['roles'] = dict(getattr(behavior, 'roles', {}))
                    r['control_level'] = behavior.control_level
                    r['control_level_label'] = behavior.metrics.get(
                        'control_level_label')
                    r['engagement_authority'] = behavior.authority
                    r['engagement_authority_label'] = behavior.metrics.get(
                        'engagement_authority_label')
                    r['control_objective'] = behavior.objective
                    r['sensor_radius_m'] = behavior.params.get('sensor_radius_m')
                    r['standoff_m'] = behavior.params.get('standoff_m')
                    r['duration_s'] = behavior.params.get('duration_s')
                    r['target_start_mode'] = behavior.params.get(
                        'target_start_mode', 'task_clock')
                    r['center'] = [round(v, 2) for v in behavior.center]
                    r['perimeter_m'] = round(behavior.perimeter_m, 1)
                    # 每段边界的折线：画图/覆盖核对都以这条线为准，前端不再
                    # 自己按弧长重算（重算就会和规划层看到的不是同一条边界）。
                    r['sectors'] = []
                    for post in behavior.post_list:
                        if not post.get('sector'):
                            continue
                        r['sectors'].append(dict(
                            pid=post['pid'], role=post['role'],
                            sector=list(post['sector']),
                            boundary=geom.sector_vertices(
                                behavior.polygon, post['sector'][0],
                                post['sector'][1])))
                    r['targets'] = [dict(target_id=x.id,
                                         authorized=x.authorized,
                                         compliance=x.compliance,
                                         start=[round(v, 2) for v in x.start],
                                         goal=[round(v, 2) for v in x.goal],
                                         speed_mps=x.speed,
                                         t_start_s=x.t_start)
                                    for x in behavior.targets]
                else:
                    r['posts'] = [[round(p[0], 2), round(p[1], 2)]
                                  for p in behavior.posts]
                    r['intruder_start'] = [round(v, 2)
                                           for v in behavior.intruder_start]
                    r['ring_radius'] = behavior.params.get('ring_radius')
            elif behavior.kind == 'recon':
                if isinstance(behavior, AreaReconBehavior):
                    r.update(area=behavior.area,
                             sensor_radii=behavior.sensor_radii,
                             air_pids=sorted(behavior.air_pids),
                             cells=len(behavior.cells),
                             cell_size_m=float(behavior.params['cell']),
                             coverage_target=behavior.params['coverage_target'],
                             coverage_definition='可侦察室外网格覆盖')
                    if behavior.tracking_target:
                        r['tracking_target'] = behavior.tracking_target
                else:
                    r['area_radius'] = behavior.params.get('area_radius')
                    r['sensor_radius'] = behavior.params.get('sensor_radius')
            elif behavior.kind == 'assault':
                r['staging'] = [[round(p[0], 2), round(p[1], 2)]
                                for p in behavior.staging]
                r['objective'] = [[round(p[0], 2), round(p[1], 2)]
                                  for p in behavior.objective]
                # T-ASL 效果判定要素：角色/效果分类/目标绑定/逐项结果初值
                r['roles'] = dict(getattr(behavior, 'roles', {}))
                r['assault_pids'] = list(getattr(behavior, 'assault_pids',
                                                 behavior.pids))
                r['pids'] = list(behavior.pids)
                r['effect_kind'] = behavior.effect_kind
                r['effect'] = behavior.effect_label
                r['target_id'] = behavior.target_id
                r['attempt'] = behavior.attempt
                r['result_items'] = [dict(x) for x in behavior.result_items]
                r['assessment_post'] = (
                    [round(v, 2) for v in behavior.assessment_post]
                    if getattr(behavior, 'assessment_post', None) else None)
                r['air_altitude'] = dict(behavior.params.get('air_altitude') or {})
                r['climb_rate'] = behavior.params.get('climb_rate')
                # 探测半径：工作台画"智能体探测范围"用，不参与判定
                r['sensor_radius_m'] = behavior.params.get('sensor_radius_m')
                r['platform_caps'] = dict(getattr(behavior, 'platform_caps', {}) or {})
                # 观感层参数：观察位/观察环、集结环、到位后的游走与盘旋半径。
                # 前端只按这些记录值画圈，不自己推半径（半径一律来自场景/行为参数）。
                r['observation'] = (
                    [round(v, 2) for v in behavior.observation]
                    if getattr(behavior, 'observation', None) else None)
                for key in ('observe_radius', 'confirm_radius', 'staging_radius',
                            'loiter_radius_m', 'loiter_period_s',
                            'air_orbit_radius_m', 'air_orbit_period_s'):
                    value = behavior.params.get(key)
                    if value is not None:
                        r[key] = value
            elif behavior.kind == 'hold' and getattr(behavior, 'positions', None):
                # T-HLD 要点坚守：要点、阵位（含朝向）、威胁方向、预备队/支援位、
                # 判定口径与自动轮换/增援规则。回放只画这一份结构，不再自己
                # 按威胁方向重算阵位。
                r['key_point'] = [round(v, 2) for v in behavior.key_point]
                r['positions'] = [dict(item) for item in behavior.positions]
                r['threats'] = [dict(item) for item in behavior.threats]
                # 威胁扇区按后端同一套角度算好，前端只按顶点画，不重算几何
                r['threat_sectors'] = [
                    dict(item, polygon=[
                        [round(p[0], 2), round(p[1], 2)] for p in
                        geom.threat_sector(behavior.key_point,
                                           item.get('bearing_deg', 0.0),
                                           item.get('width_deg', 60.0),
                                           behavior.sensor_radius * 0.9)])
                    for item in behavior.threats]
                r['observation_samples'] = [
                    [round(p['point'][0], 2), round(p['point'][1], 2)]
                    for p in behavior.samples]
                r['posts'] = [[round(p[0], 2), round(p[1], 2)]
                              for p in behavior.post_point.values()]
                r['standby'] = [round(v, 2) for v in behavior.reserve_point]
                r['support_points'] = [[round(p[0], 2), round(p[1], 2)]
                                       for p in behavior.support_points]
                r['relay_point'] = [round(v, 2) for v in behavior.relay_point]
                r['roles'] = dict(behavior.role)
                r['min_on_post'] = behavior.min_on_post
                r['hold_criteria'] = behavior.criteria
                r['hold_criteria_label'] = behavior.metrics.get(
                    'hold_criteria_label')
                r['sensor_radius_m'] = behavior.sensor_radius
                r['observation_ring_m'] = behavior.observation_ring_m
                r['observation_gap_max_s'] = behavior.params.get(
                    'observation_gap_max_s')
                r['patrol_enabled'] = bool(getattr(behavior, 'patrol_enabled',
                                                   False))
                r['patrol_radius_m'] = getattr(behavior, 'patrol_radius', 0.0)
                r['patrol_speed_mps'] = getattr(behavior, 'patrol_speed', None)
                r['post_tolerance_m'] = getattr(behavior, 'post_tolerance', None)
                # 空中观察席（防空/对空警戒）：席位、盘旋半径/高度与周期
                r['air_units'] = list(getattr(behavior, 'air_pids', []))
                r['air_altitude_m'] = getattr(behavior, 'air_altitude_m', None)
                # 画圈用有效半径（对空威胁区相交时已收缩），配置值另存。
                r['air_orbit_radius_m'] = getattr(
                    behavior, 'air_orbit_radius_effective_m',
                    behavior.params.get('air_orbit_radius_m'))
                r['air_orbit_radius_configured_m'] = behavior.params.get(
                    'air_orbit_radius_m')
                r['air_orbit_period_s'] = behavior.params.get('air_orbit_period_s')
                r['min_key_point_coverage'] = behavior.params.get(
                    'min_key_point_coverage')
                r['duration_s'] = behavior.params.get('duration_s')
                r['relief'] = dict(behavior.params.get('relief') or {})
                r['reinforce'] = dict(behavior.params.get('reinforce') or {})
                r['withdraw'] = dict(behavior.params.get('withdraw') or {})
                r['scope'] = behavior.metrics.get('scope')
            elif behavior.kind == 'hold':
                r['posts'] = [[round(p[0], 2), round(p[1], 2)]
                              for p in behavior.posts]
                r['standbys'] = [[round(p[0], 2), round(p[1], 2)]
                                 for p in behavior.standbys]
        except AttributeError:
            pass
        return r

    def _step_behavior(self, job, now, events):
        """驱动一个行为步：推进状态机、写回位姿、按推进度映射进度。

        返回 True 表示行为已完成（作业级 done）。行为层产生的细分事件
        （checkpoint_visited / cycle_completed / phase 等）单独收集进
        self.behavior_events，由 simulate 层追加进审计，不进 coordinator
        的反馈校验通道。
        """
        runner = job["bh_runner"]
        bh_job = job["bh_job"]
        behavior = runner.behavior
        participating = {}
        for active_job in self.jobs.values():
            for member in active_job["members"].values():
                pid = member["wire"]["command"]["worker_id"]
                st = self.platforms.get(pid)
                if (st is None or st.get("dead")
                        or abs(float(st.get("z") or 0.0)) > 1e-6
                        or pid in runner.agents):
                    continue
                participating[pid] = tuple(st["pos"])
        runner.peer_ground_positions = participating
        commands = {m['wire']['command']['worker_id']:m['wire']['command'] for m in job['members'].values()}
        def record(pid, offset, duration, phase, before, after):
            if pid in commands and not self.platforms[pid]['dead']:
                self.motion_offsets[pid] = offset + duration
                if self.motion_recorder:
                    self.motion_recorder(pid, now+offset, duration, phase, before, after, commands[pid])
        done = runner.step(record)
        # 行为层每个 0.1 s 控制拍都推进一次位姿。把本仿真步新增的逐拍
        # 采样作为一条增量记录写入审计，供回放还原真实折线；只用一个
        # wrapper，避免 50 台平台产生逐平台碎片消息。
        sample_cursor = job.get("bh_seen_samples", 0)
        new_samples = runner.samples[sample_cursor:]
        job["bh_seen_samples"] = len(runner.samples)
        if new_samples:
            compact_samples = []
            for sample in new_samples:
                row = json.loads(json.dumps(sample))
                # 调试快照已由 behavior_detail 每步保存一次，逐拍轨迹不再
                # 重复携带同一份 debug 对象。
                row.pop("debug", None)
                row["local_t"] = row.get("t", 0)
                row["t"] = round(job["bh_origin_s"] + float(row.get("t", 0)), 6)
                compact_samples.append(row)
            self.behavior_events.append(dict(
                kind="behavior_samples", job_id=bh_job["job_id"],
                command_ids={m["wire"]["command"]["worker_id"]: m["wire"]["command"]["command_id"]
                             for m in job["members"].values()},
                recorded_at_sim_s=now,
                samples=compact_samples))
        # Diagnostic snapshots are emitted as audit-only data. They never enter
        # coordinator feedback validation and cannot change execution decisions.
        route_cursor = job.get("bh_seen_routes", 0)
        new_routes = []
        for route in runner.routes[route_cursor:]:
            row = dict(route)
            row["recorded_at_sim_s"] = now
            new_routes.append(row)
        job["bh_seen_routes"] = len(runner.routes)
        detail = dict(kind="behavior_detail", job_id=bh_job["job_id"],
                      local_t=round(runner.time, 3), phase=behavior.phase,
                      debug=behavior.debug() if hasattr(behavior, 'debug') else {},
                      params=dict(behavior.params), routes=new_routes)
        if isinstance(behavior, AreaReconBehavior):
            detail["recon_sweep"] = behavior.drain_sweep()
            if behavior.target_sample and not behavior.relay_target:
                self.behavior_events.append(dict(
                    behavior.target_sample, job_id=bh_job["job_id"],
                    kind="recon_target_sample",
                    recorded_at_sim_s=now))
        self.behavior_events.append(json.loads(json.dumps(detail)))
        # 位姿写回（行为层在场景坐标推进；空中平台 z 为当前高度）
        for pid, agent in runner.agents.items():
            st = self.platforms.get(pid)
            if st is not None:
                st["pos"] = (agent.x, agent.y)
                st["z"] = float(agent.z)
                st["yaw"] = agent.yaw
                st["_return_nav"] = runner.nav
        # 弹药写回：突击行为的齐射消耗同步到平台状态（反馈里可见）
        if hasattr(behavior, "ammo"):
            for pid, val in behavior.ammo.items():
                st = self.platforms.get(pid)
                if st is not None:
                    st["ammo"] = int(val)
        # 移动电按实际行程记：行为层接管了机动/集结/突击/撤离的全部位移，
        # 原来在"到达即出账"的口径会漏掉这一段。口径与替身一致：
        # 行程 / 速度 = 步数，步数 × move_cost = 电量。
        odo = job.setdefault("bh_odo", {})
        empty = job.setdefault("bh_empty", set())
        for key, m in list(job["members"].items()):
            command = m["wire"]["command"]
            pid = command["worker_id"]
            agent = runner.agents.get(pid)
            st = self.platforms.get(pid)
            if agent is None or st is None or st["dead"]:
                continue
            walked = agent.odometer - odo.get(pid, 0.0)
            if walked <= 0:
                continue
            odo[pid] = agent.odometer
            speed = max(agent.speed, 1e-6)
            st["battery"] = max(
                0.0, st["battery"]
                - walked / speed * command["delivery"]["move_cost"])
            # 电量耗尽：本层不把它当硬中止（演示只做规划/行为），但必须显式
            # 记一条事件，否则"电量归零却仍在突进"会悄悄留在轨迹里。
            if st["battery"] <= 0.0 and pid not in empty:
                empty.add(pid)
                self.behavior_events.append(dict(
                    t=round(runner.time, 2), recorded_at_sim_s=now,
                    kind="energy_depleted", job_id=bh_job["job_id"],
                    pid=pid, odometer=round(agent.odometer, 1),
                    note="续航按 move_cost 记账已归零，本演示未把电量作为中止条件"))
        # 行为进度 → 作业进度（progress_frac ∈ [0,1]，done 恒 1.0）
        frac = behavior.progress_frac()
        # A multi-phase behavior can legitimately change its progress formula
        # (for example reconnaissance switches from coverage to target
        # tracking).  The coordinator treats any decrease as invalid feedback
        # and, after the stall grace, reassigns healthy members.  Keep the
        # command's monotonic progress while allowing phase-specific fractions
        # below 1.0 until the behavior has actually finished.
        calculated = min(job["work"], job["work"] * frac)
        job["progress"] = max(float(job.get("progress") or 0.0), calculated)
        # 行为事件（增量）收集：每个 job 各自记录已收集事件数（多 job
        # 并发推进时不能共用全局计数器，否则互相覆盖导致重复/漏收）。
        n_ev = job.get("bh_seen_events", 0)
        for ev in runner.events[n_ev:]:
            self.behavior_events.append(dict(ev))
        job["bh_seen_events"] = len(runner.events)
        # 行为阶段作为 feedback 的 phase 供工作台展示
        job["_phase"] = behavior.phase
        return done

    def _poll_behavior(self, job, now, events):
        """行为模式下的一步推进 + 反馈（复用 progress/succeeded 反馈语义）。

        作业结算：行为给出 result（T-ASL 效果判定）时按 overall 结算——
        "行为走完"不冒充"任务成功"，弹药耗尽/超时/评估未达成都按 failed
        回给 coordinator，由其重试或终审。
        """
        job_id = job["bh_job"]["job_id"]
        members = job["members"]
        behavior = job["bh_runner"].behavior
        done = self._step_behavior(job, now, events)
        # 行为阶段作为 phase；作业级进度 = progress_frac 映射值
        phase = job.get("_phase") or behavior.phase
        progress = job["progress"]
        status, note = "succeeded", None
        result = getattr(behavior, "result", None)
        recon_result = done and isinstance(behavior, AreaReconBehavior)
        relay_verdict = done and behavior.params.get("relay_verdict")
        verdict = getattr(behavior, "verdict", None) or {}
        hold_verdict_not_succeeded = (
            done and behavior.kind == "hold" and bool(verdict)
            and verdict.get("verdict") != "succeeded")
        containment_timed_out = (
            done and isinstance(behavior, ContainmentBehavior)
            and behavior.params.get("target_start_mode") == "after_control"
            and verdict.get("timeout"))
        if recon_result:
            status = result["overall"]
            tracking = result.get("tracking") or {}
            if result.get("termination") == "track_timeout":
                note = ("可侦察室外网格覆盖 %.1f%% 已达标；目标区外持续跟踪未完成，"
                        "按跟踪宽限截止返航" % (result["coverage"] * 100))
            elif tracking and not tracking.get("completed"):
                note = ("可侦察室外网格覆盖 %.1f%%；目标跟踪未完成（终止:%s）"
                        % (result["coverage"] * 100,
                           result.get("termination") or "未知"))
            else:
                note = ("可侦察室外网格覆盖 %.1f%% / 目标 %.1f%%；目标跟踪%s" % (
                    result["coverage"] * 100,
                    result["coverage_target"] * 100,
                    "完成" if tracking.get("completed") else "无此项"))
        elif hold_verdict_not_succeeded:
            # KeepBehavior 的最终裁决是任务级事实：行为流程走完、完成撤离，
            # 并不等于控制权或行动目标达成。控制权丧失等情况必须下发 failed，
            # 不能因为状态机正常结束而记成 succeeded。场景没有提供敌方事件时，
            # 保留 pending 表示“控制过程完成、战果无法验证”，不把数据缺口
            # 误报为执行失败。
            status = verdict.get("verdict") or "failed"
            if status not in ("failed", "pending"):
                status = "failed"
            note = verdict.get("reason") or "要点坚守裁决未达成"
        elif containment_timed_out:
            status, note = "failed", verdict["reason"]
        elif relay_verdict:
            verdict = behavior.verdict
            status = "succeeded" if verdict["verdict"] == "succeeded" else "failed"
            note = verdict["reason"]
        elif done and result is not None:
            verified = "已验证" if result.get("verified") else "桩判定·未验证"
            adjudicator = result.get("adjudicator")
            if result.get("overall") == "succeeded":
                note = "效果判定:成功（%s·%s）" % (adjudicator, verified)
            else:
                status = "failed"
                note = "效果判定:%s；终止:%s（%s·%s）" % (
                    result.get("overall"),
                    result.get("termination") or "评估未达成",
                    adjudicator, verified)
            payload = dict(t=round(job["bh_runner"].time, 2),
                           recorded_at_sim_s=now,
                           kind="behavior_result", job_id=job_id)
            payload.update(json.loads(json.dumps(result)))
            self.behavior_events.append(payload)
        for key, m in list(members.items()):
            command = m["wire"]["command"]
            st = self.platforms.get(command["worker_id"])
            if st is None or st["dead"]:
                continue
            try:
                frac = behavior.subtask_progress(command['worker_id'])
            except (KeyError, TypeError, ValueError):
                frac = behavior.progress_frac()
            if done:
                event = self._event(m["wire"], now, status,
                                    progress if recon_result else job["work"],
                                    phase=phase, note=note,
                                    subtask_progress=1.0 if status=="succeeded" else frac)
                if ((recon_result or relay_verdict
                     or hold_verdict_not_succeeded
                     or containment_timed_out)
                        and status in ("failed", "pending")):
                    event["terminal"] = True
                if status == 'failed':
                    event['attempt_complete'] = True
                elif status == 'pending':
                    event['attempt_complete'] = True
                    event['inconclusive'] = True
                if status == 'failed' and (
                        hold_verdict_not_succeeded or containment_timed_out):
                    event["final_failure"] = True
                events.append(event)
                st["active"] = False
                members.pop(key, None)
            else:
                events.append(self._event(m["wire"], now, "progress",
                                          progress, phase=phase, subtask_progress=frac))
        if done and not members:
            del self.jobs[job_id]

    def drain_behavior_events(self):
        """取出并清空行为层累计事件，供 simulate 层合并进审计。"""
        out, self.behavior_events = self.behavior_events, []
        return out

    def relay_sample(self, now):
        relay = self.relay_target
        if relay and relay.started_at is not None:
            return dict(kind="relay_target_sample", job_id=relay.spec["source_job_id"],
                        target_id=relay.spec["target_id"],
                        pos=[round(v, 3) for v in relay.position(now)])

    def returns_pending(self):
        return any(state["status"] == "returning" for state in self.return_state.values())

    def _orbit_state(self, st, center, profile, key, radius=None):
        speed = max(0.01, float(profile["speed"]))
        orbit = st.get(key)
        if orbit is None or not orbit.matches(center):
            orbit = st[key] = motion.AirLoiter(
                center, speed, radius=profile.get("orbit_radius") or 3.0,
                max_yaw_rate=profile.get("orbit_yaw_rate", 0.35))
        moved = 0.0
        for _ in range(TWIST_TICKS_PER_STEP):
            pose, distance = orbit.step(
                motion.Pose(*st["pos"], st["z"], st["yaw"]),
                1.0 / TWIST_TICKS_PER_STEP, radius=radius)
            st["pos"] = (pose.x, pose.y)
            st["yaw"] = pose.yaw
            moved += distance
        st["battery"] = max(
            0.0, st["battery"] - moved / speed * profile["move_cost"])

    def _descend_home(self, st, home, state, profile):
        st["z"] = max(0.0, st["z"] - 3.0)
        orbit = st.get("_return_loiter")
        if orbit is None:
            orbit = st["_return_loiter"] = motion.AirLoiter(
                home, profile["speed"], radius=profile.get("orbit_radius") or 3.0,
                max_yaw_rate=profile.get("orbit_yaw_rate", 0.35))
        self._orbit_state(
            st, home, profile, "_return_loiter",
            radius=(orbit.radius * st["z"]
                    / max(state["cruise"], 1e-6)))

    def step_returns(self, now, reserved):
        """推进无后续分配的空闲成员；地面绕障，空中到家后再降落。"""
        from city_nav import NavError
        before_return = {pid:self._pose(st) for pid,st in self.platforms.items()}
        for pid, st in self.platforms.items():
            if (pid not in self.home or st["active"] or st["dead"]
                    or st.get("disabled")):
                continue
            profile = st.get("return_profile")
            if not profile:
                continue
            if pid in reserved:
                if (self.motion == "real" and profile["can_climb"]
                        and st["z"] > 1e-6
                        and st.get("_air_moved_at") != now):
                    orbit = st.get("_waiting_loiter")
                    center = orbit.center if orbit else st["pos"]
                    self._orbit_state(
                        st, center, profile, "_waiting_loiter")
                    st["_air_moved_at"] = now
                    self.behavior_events.append(dict(
                        kind="air_wait_sample", pid=pid,
                        recorded_at_sim_s=now, phase="loiter",
                        pos=list(st["pos"]), z=st["z"], yaw=st["yaw"],
                        battery=st["battery"]))
                continue
            st.pop("_waiting_loiter", None)
            home = self.home[pid]
            air = profile["can_climb"]
            state = self.return_state.get(pid)
            if state is None:
                pos, z = st["pos"], st["z"]
                path = [pos, home]
                nav = st.get("_return_nav") or self.nav
                route_nav = (getattr(nav, "air_threat_nav", None)
                             if air else nav)
                scoped_router = (getattr(nav, "route_router", None)
                                 or getattr(nav, "threat_router", None))
                if (self.motion == "real" and scoped_router is not None
                        and math.dist(pos, home) > 1e-6):
                    try:
                        path = [list(point) for point in scoped_router.route(
                            pos, home, is_air=bool(air),
                            altitude_m=(max(z, 25.0) if air else None)).path]
                    except ValueError as exc:
                        self.return_state[pid] = dict(status="failed", home=list(home))
                        self.behavior_events.append(dict(
                            kind="return_failed", pid=pid,
                            recorded_at_sim_s=now, pos=list(pos), z=z,
                            reason="threat_route:%s" % exc))
                        continue
                elif (self.motion == "real" and route_nav is not None
                      and math.dist(pos, home) > 1e-6):
                    try:
                        path = route_nav.plan(pos, home, densify=0)["path"]
                    except (NavError, ValueError) as exc:
                        self.return_state[pid] = dict(status="failed", home=list(home))
                        self.behavior_events.append(dict(kind="return_failed", pid=pid,
                            recorded_at_sim_s=now, pos=list(pos), z=z, reason=str(exc)))
                        continue
                cruise = max(z, 25.0) if air and self.nav is not None else z
                index = len(path) if math.dist(pos, home) <= 1e-6 else 1
                state = dict(status="returning", home=list(home), path=path, index=index,
                             started=now, cruise=cruise)
                self.return_state[pid] = state
                self.behavior_events.append(dict(kind="return_started", pid=pid,
                    recorded_at_sim_s=now, pos=list(pos), z=z, home=[*home, 0.0],
                    path=[list(p) for p in path]))
                if self.motion == "real" and (index < len(path) or (air and z > 0)):
                    continue
            if state["status"] != "returning":
                continue
            phase = "return"
            if self.motion == "teleport":
                st["pos"], st["z"], state["index"] = home, 0.0, len(state["path"])
            elif air and state["index"] < len(state["path"]) and st["z"] < state["cruise"] - 1e-6:
                st["z"] = min(state["cruise"], st["z"] + 3.0)
                orbit = st.get("_return_loiter")
                center = orbit.center if orbit else st["pos"]
                self._orbit_state(
                    st, center, profile, "_return_loiter")
            elif air and state["index"] < len(state["path"]):
                st.pop("_return_loiter", None)
                remaining = max(0.01, float(profile["speed"]))
                while remaining > 1e-9 and state["index"] < len(state["path"]):
                    target = state["path"][state["index"]]
                    x, y = st["pos"]
                    dx, dy = target[0] - x, target[1] - y
                    length = math.hypot(dx, dy)
                    step = min(remaining, length)
                    if length > 1e-9:
                        st["yaw"] = math.atan2(dy, dx)
                        st["pos"] = (x + dx / length * step,
                                     y + dy / length * step)
                    remaining -= step
                    if length <= step + 1e-9:
                        state["index"] += 1
                st["battery"] = max(0.0, st["battery"] - profile["move_cost"])
            elif state["index"] < len(state["path"]):
                st.pop("_return_loiter", None)
                limits = limits_for(
                    profile.get("kind") or "UGV", profile["speed"])
                remaining = max(0.01, float(profile["speed"]))
                while remaining > 1e-6 and state["index"] < len(state["path"]):
                    target = state["path"][state["index"]]
                    x, y = st["pos"]
                    dx, dy = target[0] - x, target[1] - y
                    length = math.hypot(dx, dy)
                    if length <= 0.6 and length <= remaining:
                        st["pos"] = tuple(target)
                        remaining -= length
                        state["index"] += 1
                        continue
                    desired = math.atan2(dy, dx)
                    error = motion.wrap_pi(desired - st["yaw"])
                    if abs(error) > 0.5:
                        st["yaw"], _ = turn_toward(
                            st["yaw"], desired, limits.max_yaw_rate, 1.0)
                        break
                    st["yaw"], _ = turn_toward(
                        st["yaw"], desired, limits.max_yaw_rate, 1.0)
                    step = min(remaining, length)
                    st["pos"] = (
                        x + step * math.cos(st["yaw"]),
                        y + step * math.sin(st["yaw"]))
                    remaining -= step
                    if length <= step + 1e-9:
                        state["index"] += 1
                st["battery"] = max(0.0, st["battery"] - float(profile["move_cost"]))
            elif air and st["z"] > 0:
                phase = "landing"
                self._descend_home(st, home, state, profile)
            elif air and math.dist(st["pos"], home) > 1e-6:
                phase = "landing"
                limits = limits_for(
                    profile.get("kind") or "PLANE", profile["speed"])
                dx, dy = home[0] - st["pos"][0], home[1] - st["pos"][1]
                length = math.hypot(dx, dy)
                desired = math.atan2(dy, dx)
                error = motion.wrap_pi(desired - st["yaw"])
                if abs(error) > 0.5:
                    st["yaw"], _ = turn_toward(
                        st["yaw"], desired, limits.max_yaw_rate, 1.0)
                else:
                    st["yaw"], _ = turn_toward(
                        st["yaw"], desired, limits.max_yaw_rate, 1.0)
                    step = min(profile["speed"], length)
                    st["pos"] = (
                        st["pos"][0] + step * math.cos(st["yaw"]),
                        st["pos"][1] + step * math.sin(st["yaw"]))
            arrived = (
                state["index"] >= len(state["path"])
                and (not air
                     or (st["z"] <= 1e-6
                         and math.dist(st["pos"], home) <= 1e-6)))
            if arrived:
                st["pos"] = tuple(home)
                st["z"] = 0.0
            self.behavior_events.append(dict(kind="return_sample", pid=pid,
                phase="returned" if arrived else phase,
                recorded_at_sim_s=now, pos=[round(v, 3) for v in st["pos"]],
                z=round(st["z"], 3), yaw=round(st["yaw"], 4), battery=round(st["battery"], 3)))
            if arrived:
                state.update(status="returned", finished=now)
                self.behavior_events.append(dict(kind="return_completed", pid=pid,
                    recorded_at_sim_s=now, pos=list(st["pos"]), z=st["z"], landed=bool(air)))

        if self.motion_recorder:
            active_commands={m['wire']['command']['worker_id']:m['wire']['command'] for job in self.jobs.values() for m in job['members'].values()}
            for pid,st in self.platforms.items():
                if st.get('dead') or st.get('disabled') or not st.get('return_profile'):
                    continue
                offset=min(1.0,self.motion_offsets.get(pid,0.0))
                if offset>=1.0-1e-6:
                    continue
                returned=self.return_state.get(pid,{})
                phase='work' if st.get('active') else ('loiter' if pid in reserved else 'landing' if st['z']<before_return[pid][2] else 'return')
                self.motion_recorder(pid,now+offset,1.0-offset,phase,before_return[pid],self._pose(st),active_commands.get(pid))

    # ---------------- 推进与反馈 ----------------
    def _step_air_member(self, member, st, delivery, now):
        command = member['wire']['command']
        """飞到作业驻点后持续盘旋；爬升和作业期间都不在空中悬停。"""
        goal = member["goal"]
        center = (goal["x"], goal["y"])
        speed = max(
            0.01, float((delivery.get("motion_caps") or {}).get(
                "max_linear", delivery["speed"])))
        altitude = member.setdefault(
            "air_altitude", float(goal.get("z") or st["z"]))
        dt = 1.0 / TWIST_TICKS_PER_STEP
        limits = limits_for(delivery.get("kind") or "PLANE", speed)
        orbit_distance = 0.0
        for control_tick in range(TWIST_TICKS_PER_STEP):
            before_pose = self._pose(st)
            st["z"] += max(
                -min(speed, 3.0) * dt,
                min(min(speed, 3.0) * dt, altitude - st["z"]))
            remaining = dt
            if not member.get("xy_reached"):
                dx, dy = (
                    center[0] - st["pos"][0],
                    center[1] - st["pos"][1])
                distance = math.hypot(dx, dy)
                desired = math.atan2(dy, dx)
                error = motion.wrap_pi(desired - st["yaw"])
                st["yaw"] = desired
                st["_air_w"] = 0.0
                target_v = speed
                if abs(error) > 0.25:
                    target_v = max(
                        speed * 0.25,
                        speed * (1.0 - 0.65
                                 * min(abs(error), math.pi) / math.pi))
                if distance < 2.0:
                    target_v = min(
                        target_v, max(speed * 0.25, distance))
                current_v = st.get("_air_v", speed)
                accel = (limits.max_accel if current_v < target_v
                         else limits.max_decel)
                st["_air_v"] = approach(
                    current_v, target_v, accel * dt)
                step = min(st["_air_v"] * dt, distance)
                st["pos"] = (
                    st["pos"][0] + step * math.cos(desired),
                    st["pos"][1] + step * math.sin(desired))
                remaining -= step / max(st["_air_v"], 1e-6)
                if distance <= speed * dt + 0.5 and abs(error) < 0.45:
                    member["xy_reached"] = True
            if (member.get("xy_reached") and st["z"] > 1e-6
                    and remaining > 1e-9):
                orbit = member.setdefault(
                    "air_loiter", motion.AirLoiter(center, speed))
                pose, moved = orbit.step(
                    motion.Pose(*st["pos"], st["z"], st["yaw"]),
                    remaining)
                st["pos"] = (pose.x, pose.y)
                st["yaw"] = pose.yaw
                orbit_distance += moved
            if self.motion_recorder:
                self.motion_recorder(command["worker_id"],now+control_tick*dt,dt,"work" if member.get("charged") else "travel",before_pose,self._pose(st),command)
            self.motion_offsets[command["worker_id"]] = (control_tick+1)*dt
        st["_air_moved_at"] = now
        st["battery"] = max(
            0.0, st["battery"]
            - orbit_distance / speed * float(delivery["move_cost"]))

    def poll(self, now):
        self.motion_offsets.clear()
        events = []
        # 绝对步时间线事件：now 命中的全部执行（同一步多事件不吞）。
        self._apply_timed_events(now, events)
        for job_id in list(self.jobs.keys()):
            job = self.jobs[job_id]
            members = job["members"]

            # 任务级失败注入（仅第一次尝试）
            fail_at = self.fail_once.get(job_id)
            if fail_at is not None:
                first_cmds = [m for m in members.values()
                              if m["wire"]["command"]["attempt"] == 1]
                if first_cmds and all(
                        now - m["wire"]["command"]["issued_sim_s"] >= fail_at
                        for m in first_cmds):
                    for key, m in list(members.items()):
                        st = self.platforms.get(
                            m["wire"]["command"]["worker_id"])
                        if st is not None:
                            st["active"] = False
                        events.append(self._event(
                            m["wire"], now, "failed", job["progress"],
                            note="演示注入的任务级失败"))
                    del self.jobs[job_id]
                    continue

            # 行为模式：所有成员到位后，由行为状态机接管"到位后的动作"，
            # 不再原地刷 work_rate。行为步驱动位姿、映射进度、收集细分事件。
            if self._behavior_on(job_id) and job.get("bh_runner") is not None:
                self._poll_behavior(job, now, events)
                continue
            if self._behavior_on(job_id):
                runner = self._ensure_behavior(job, now)
                if runner is not None:
                    self._poll_behavior(job, now, events)
                    continue

            # 推进每个成员：瞬移模式到开工时刻瞬移到达；真实模式逐步推进
            gained = 0.0
            for key, m in list(members.items()):
                command = m["wire"]["command"]
                delivery = command["delivery"]
                st = self.platforms.get(command["worker_id"])
                if st is None or st["dead"]:
                    continue                     # 失联平台不再贡献
                if (command["attempt"] == 1 and now < command["issued_sim_s"]
                        + self.delay_once.get(job_id, 0)):
                    continue  # timeout demo must stall real motion as well as teleport.
                if self.motion == "real":
                    if delivery.get("can_climb"):
                        self._step_air_member(m, st, delivery, now)
                        if not m["charged"]:
                            if (m.get("xy_reached")
                                    and abs(st["z"] - m["air_altitude"])
                                    <= 0.5):
                                m["charged"] = True
                                st["battery"] = max(
                                    0.0, st["battery"]
                                    - m["travel_steps"]
                                    * delivery["move_cost"])
                            else:
                                continue
                    elif not m["charged"]:
                        # 地面真实运动：闭环控制器推进到航点。
                        # 每个规划步内部推进 TWIST_TICKS_PER_STEP 拍
                        for control_tick in range(TWIST_TICKS_PER_STEP):
                            before_pose = self._pose(st)
                            pose = motion.Pose(st["pos"][0], st["pos"][1],
                                               st["z"], st["yaw"])
                            goal = m["goal"]
                            if m.get("route"):
                                route = m["route"]
                                i = m.get("route_i", 1)
                                while (i < len(route) - 1
                                       and math.hypot(st["pos"][0] - route[i][0],
                                                      st["pos"][1] - route[i][1]) < 0.7):
                                    i += 1
                                m["route_i"] = i
                                waypoint = route[min(i, len(route) - 1)]
                                goal_pose = motion.Pose(
                                    waypoint[0], waypoint[1], 0.0, 0.0)
                            else:
                                goal_pose = motion.Pose(
                                    goal["x"], goal["y"],
                                    goal.get("z", 0.0), goal.get("yaw", 0.0))
                            tw = m["ctl"].update(pose, goal_pose, dt=1.0 / TWIST_TICKS_PER_STEP)
                            if tw.is_stop():
                                break
                            # 替身动力学：按 Twist 积分推进位姿
                            dt = 1.0 / TWIST_TICKS_PER_STEP
                            st["yaw"] += tw.angular_z * dt
                            st["pos"] = (st["pos"][0]
                                         + tw.linear_x * math.cos(st["yaw"]) * dt,
                                         st["pos"][1]
                                         + tw.linear_x * math.sin(st["yaw"]) * dt)
                            st["z"] += tw.linear_z * dt
                            if self.motion_recorder:
                                self.motion_recorder(command['worker_id'],now+control_tick*dt,dt,'travel',before_pose,self._pose(st),command)
                            self.motion_offsets[command['worker_id']] = (control_tick+1)*dt
                        if m["ctl"].arrived(
                                motion.Pose(st["pos"][0], st["pos"][1],
                                            st["z"], st["yaw"]),
                                motion.Pose(m["goal"]["x"], m["goal"]["y"],
                                            m["goal"].get("z", 0.0),
                                            m["goal"].get("yaw", 0.0))):
                            # 到达：移动电按实际推进的步数记清
                            m["charged"] = True
                            st["battery"] = max(
                                0.0, st["battery"]
                                - m["travel_steps"] * delivery["move_cost"])
                        else:
                            continue          # 还在途，本步不贡献作业
                else:
                    # 瞬移语义：到开工时刻即视为到达
                    if now < m["arrival"]:
                        continue
                    if not m["charged"]:
                        m["charged"] = True
                        st["pos"] = m["target"]
                        st["battery"] = max(
                            0.0, st["battery"]
                            - m["travel_steps"] * delivery["move_cost"])
                # 到位后：作业贡献。行为模式下不刷 work_rate——到位只是
                # "抵达作业区"，之后由行为状态机接管（等全员到位切行为），
                # 否则 crew>1 的作业会在行为启动前就被 work_rate 刷完。
                if not self._behavior_on(job_id):
                    contribution = delivery["work_rate"] * self.slow_once.get(job_id, 1.0)
                    if m.get('share') is not None:
                        contribution = min(contribution, max(0.0, m['share'] - m['contributed']))
                        m['contributed'] += contribution
                    gained += contribution
                    st["battery"] = max(0.0, st["battery"]
                                        - delivery["work_cost"])

            if gained > 0:
                job["progress"] = min(job["work"], job["progress"] + gained)

            # 反馈：进度或阶段变化才发，避免每步刷屏
            done = job["progress"] >= job["work"] - 1e-6
            for key, m in list(members.items()):
                command = m["wire"]["command"]
                st = self.platforms.get(command["worker_id"])
                if st is None or st["dead"]:
                    continue
                phase = "work" if m["charged"] else "travel"
                progress = job["progress"]
                frac = min(1.0,m.get("contributed",0.0)/max(1e-9,m.get("share") or job["work"]))
                if (phase != m["last_phase"]
                        or abs(progress - (m["last_progress"] or -1)) > 1e-9):
                    m["last_phase"] = phase
                    m["last_progress"] = progress
                    if done:
                        events.append(self._event(m["wire"], now, "succeeded",
                                                  job["work"], subtask_progress=1.0))
                        st["active"] = False
                        members.pop(key, None)
                    else:
                        events.append(self._event(m["wire"], now, "progress",
                                                  progress, phase=phase, subtask_progress=frac))
            if done and not members:
                del self.jobs[job_id]
        return events
