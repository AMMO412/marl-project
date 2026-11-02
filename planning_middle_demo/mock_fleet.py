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

from contracts_v2 import PROTOCOL_V2
import containment_geom as geom
import motion


# 每个规划步内部推进的 Twist 发令拍数（约 20 Hz × 1 步 = 20 拍）。
# 真实运动模式下，一个规划步对应这多次闭环控制迭代。
TWIST_TICKS_PER_STEP = 20


class MockFleet:
    def __init__(self, fail_once=None, delay_once=None, slow_once=None,
                 motion="teleport", timed_events=None, nav=None, behavior=False,
                 behavior_params=None):
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
        self.behavior_events = []

    # ---------------- 工具 ----------------
    def _event(self, wire, now, status, progress, phase=None, note=None):
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
            if kind == "job_fail":
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
                    st["active"] = True
                    start = st["pos"]
                    delay = 0
                    if command["attempt"] == 1:
                        delay = self.delay_once.get(command["job_id"], 0)
                    job = self.jobs.setdefault(command["job_id"], dict(
                        work=float(task["work"]),
                        progress=0.0, members={}))
                    if self._behavior_on():
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
                        charged=False, last_phase=None, last_progress=None)
                    # 行为模式下位移全部由行为层推进（含机动集结），替身不再
                    # 另算一条"去作业点"的路：那条路不会被执行，却会出现在
                    # 轨迹与路由统计里，等于虚报一段行程。
                    if self.motion == "real" and not self._behavior_on():
                        # 真实运动：初始化闭环控制器，逐步推进到 goal
                        caps = delivery.get("motion_caps") or {}
                        if (self.nav is not None
                                and not bool(delivery.get("can_climb"))):
                            # 地面平台走 A* 绕障路径；空中平台越障直飞
                            st_pos = st["pos"]
                            if not self.nav.free(st_pos):
                                st_pos, _ = self.nav.nearest_free(
                                    st_pos, max_radius=6.0)
                                st["pos"] = st_pos
                            try:
                                goal_xy, _ = self.nav.nearest_free(target,
                                                                   max_radius=8.0)
                                plan = self.nav.plan(st_pos, goal_xy)
                            except Exception as exc:      # noqa: BLE001
                                replies.append(self._event(
                                    wire, now, "failed", 0.0,
                                    note="避障路径不可达：%s" % exc))
                                self.jobs.pop(command["job_id"], None)
                                continue
                            member["route"] = plan["path"]
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
                                           source="approach_astar")))
                            goal = dict(x=plan["path"][-1][0],
                                        y=plan["path"][-1][1],
                                        z=0.0, yaw=0.0)
                            member["goal"] = goal
                        gains = motion.DriveGains(
                            max_linear=float(caps.get("max_linear",
                                                     delivery["speed"])),
                            max_angular=float(caps.get("max_angular", 0.5)),
                            tol_pos=float(caps.get("tol_pos", 0.5)),
                            tol_yaw=float(caps.get("tol_yaw", 0.15)))
                        member["ctl"] = motion.GoalController(
                            gains, can_climb=bool(delivery.get("can_climb")))
                    job["members"][key] = member
                    self.commands[key] = wire
                    replies.append(self._event(wire, now, "accepted", 0.0,
                                               phase="travel"))
            else:
                raise ValueError("未知指令")
            self.replies[key] = replies
            events.extend(replies)
        return events

    # ---------------- 行为层（behavior 模式） ----------------
    def _behavior_on(self):
        """行为层只在真实运动 + 有静态地图时启用。"""
        return self.behavior and self.motion == "real" and self.nav is not None

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
        if not self._behavior_on():
            return None
        runner = job.get("bh_runner")
        if runner is not None:
            return runner
        members = job["members"]
        if not members:
            return None
        from behaviors import make_behavior
        from behavior_runtime import BehaviorRunner
        bh_job = self._behavior_job_dict(job)
        pids = [m["wire"]["command"]["worker_id"]
                for m in members.values()]
        behavior = make_behavior(bh_job, self.nav, pids)
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
                             speed=float(delivery.get("speed") or speeds[pid]))
        job["bh_job"] = bh_job
        job["bh_runner"] = BehaviorRunner(self.nav, behavior, starts,
                                          speeds=speeds, caps=caps)
        job["bh_started"] = True
        job["bh_seen_events"] = 0
        job["bh_seen_routes"] = 0
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
                r['platform_caps'] = dict(getattr(behavior, 'platform_caps', {}) or {})
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
        done = runner.step()
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
        self.behavior_events.append(json.loads(json.dumps(detail)))
        # 位姿写回（行为层在场景坐标推进；空中平台 z 为当前高度）
        for pid, agent in runner.agents.items():
            st = self.platforms.get(pid)
            if st is not None:
                st["pos"] = (agent.x, agent.y)
                st["z"] = float(agent.z)
                st["yaw"] = agent.yaw
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
        job["progress"] = min(job["work"], job["work"] * frac)
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
        if done and result is not None:
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
            if done:
                events.append(self._event(m["wire"], now, status,
                                          job["work"], phase=phase, note=note))
                st["active"] = False
                members.pop(key, None)
            else:
                events.append(self._event(m["wire"], now, "progress",
                                          progress, phase=phase))
        if done and not members:
            del self.jobs[job_id]

    def drain_behavior_events(self):
        """取出并清空行为层累计事件，供 simulate 层合并进审计。"""
        out, self.behavior_events = self.behavior_events, []
        return out

    # ---------------- 推进与反馈 ----------------
    def poll(self, now):
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
            if self._behavior_on() and job.get("bh_runner") is not None:
                self._poll_behavior(job, now, events)
                continue
            if self._behavior_on():
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
                if self.motion == "real":
                    # 真实运动：用闭环控制器推进，到位靠容差判定
                    if not m["charged"]:
                        # 每个规划步内部推进 TWIST_TICKS_PER_STEP 拍
                        for _ in range(TWIST_TICKS_PER_STEP):
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
                            tw = m["ctl"].update(pose, goal_pose)
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
                if not self._behavior_on():
                    gained += delivery["work_rate"] * self.slow_once.get(
                        job_id, 1.0)
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
                if (phase != m["last_phase"]
                        or abs(progress - (m["last_progress"] or -1)) > 1e-9):
                    m["last_phase"] = phase
                    m["last_progress"] = progress
                    if done:
                        events.append(self._event(m["wire"], now, "succeeded",
                                                  job["work"]))
                        st["active"] = False
                        members.pop(key, None)
                    else:
                        events.append(self._event(m["wire"], now, "progress",
                                                  progress, phase=phase))
            if done and not members:
                del self.jobs[job_id]
        return events
