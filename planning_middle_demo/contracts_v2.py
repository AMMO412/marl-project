# -*- coding: utf-8 -*-
"""
contracts_v2.py —— 规划能力版消息契约（middle-demo/v2）

在 v1 消息骨架（run_id / plan_id / command_id / attempt / 反馈核对 /
取消-确认-重试）不变的前提下，把指令内容从"工单时长"升级为
planning/ 的通用任务语义：

  * 平台：编号对应下游 50 台编成（内部 ID rover_XX，移动话题
    /container_00/robot_XXX），带能力参数（速度/效率/续航/载荷/传感器/能否爬升）
  * 作业：工作量 + 时间窗 + 协同人数 + 载荷/传感器需求 + 目标高度
  * 指令：携带作业参数与投递信息（真实话题），下层可以独立执行
  * 反馈：accepted / progress / succeeded / failed / cancelled，
    progress 为作业级工作量（浮点），并携带位姿与电量

单位口径与 fleet.py 一致：场景坐标无量纲，时间为演示仿真步。
作业类型模板沿袭 planning/ 的五类抽象（工作量/窗口/协同差异），
只表达通用协作语义，不含武器、效能或战术参数。
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import fleet

PROTOCOL_V2 = "middle-demo/v2"

# ------------------------------------------------------------------
# 作业类型模板（配置化；五类任务名与判定口径对齐《五类作战任务》）
#
# 五类任务（按《五类作战任务》的判定语义归类）：
#   patrol   巡逻警戒：持续型 —— 规定路线/区域反复巡查，看「最大有效重访间隔」
#   blockade 区域封控：持续型 —— 全程保持通行控制 + 越界/接近事件闭合
#   recon    协同侦察：覆盖+回传 —— 合并有效覆盖达标，成果需回传并被接收确认
#   assault  机动突击：结果确认 —— 机动到位→动作结束→评估反馈确认结果达成
#   hold     要点坚守：持续型 —— 全程有效在位（数量下限）或约定状态下限
#
# 注意：本层是「规划/调度」抽象，五类任务的「完成判定」属验收层，
# 不在规划器内实现。这里仍用统一的通用协作字段表达差异（工作量/窗口/
# 协同/载荷/传感器/高度），判定语义只落进注释与中文名，不塞进规划逻辑。
#
#   work         完成所需工作量（规划抽象；持续型任务的"全程"由 window 表达）
#   window       时间窗 [最早开始, 最晚结束]（步）；持续型任务窗口即"要求时段"
#   crew         协同人数（hold/blockade 的在位/封控下限的规划近似）
#   need_payload 所需载荷
#   need_sensor  所需传感器；None 不挑
#   altitude     目标高度；>0 时只有 PLANE/WING 可接（接口事实：地面平台无 linear.z）
# ------------------------------------------------------------------
JOB_SPECS = {
    "patrol":   dict(work=12.0, window=(0, 60), crew=1, need_payload=0.0,
                     need_sensor="eo", altitude=0),
    "blockade": dict(work=18.0, window=(0, 80), crew=3, need_payload=2.0,
                     need_sensor=None, altitude=0),
    "recon":    dict(work=10.0, window=(0, 50), crew=2, need_payload=0.0,
                     need_sensor="sar", altitude=30),
    "assault":  dict(work=20.0, window=(0, 90), crew=4, need_payload=4.0,
                     need_sensor=None, altitude=0),
    "hold":     dict(work=15.0, window=(0, 70), crew=2, need_payload=1.0,
                     need_sensor="eo", altitude=0),
}
JOB_TYPE_LABELS = {
    "patrol": "巡逻警戒", "blockade": "区域封控", "recon": "协同侦察",
    "assault": "机动突击", "hold": "要点坚守",
}
# 融合层运行视图里的作业类型：4.1 任务类型 → 基座作业模板。
# 只在 build_jobs 派生 jtype 时使用（场景文件本身仍写显式 work/window/crew，
# 不塞 "type"，否则 check_scenario_v2 会按模板参数校验而拒绝）。
TASK_TYPE_TO_JOB = {"T-PTL": "patrol", "T-RCN": "recon",
                    "T-SEC": "blockade", "T-HLD": "hold"}


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class Platform:
    pid: str
    kind: str
    robot_no: int
    pos: Tuple[float, float]
    speed: float
    work_rate: float
    battery: float
    payload: float
    sensor: str
    can_climb: bool
    move_cost: float
    work_cost: float
    ammo: int = 0             # 弹药基数（发），T-ASL 齐射消耗上限
    alive: bool = True
    pos_topic: str = ""
    yaw: float = 0.0        # 当前朝向（真实运动下由反馈更新，用于 travel 估算）

    @property
    def topic(self):
        return fleet.topic_of(self.robot_no)


@dataclass
class Job:
    job_id: str
    jtype: str
    pos: Tuple[float, float]
    work: float
    window: Tuple[int, int]
    crew: int
    need_payload: float
    need_sensor: Optional[str]
    altitude: float = 0.0
    progress: float = 0.0
    status: str = "pending"      # pending/assigned/running/cancelling/succeeded/failed
    attempts: int = 0
    # 首次下发基准（deviation 检测用固定基准，不随滚动重规划漂移）
    started_at: Optional[int] = None     # 首次下发时刻
    planned_end: Optional[int] = None    # 首次计划的完工时刻
    # 场景里的 _behavior 参数（集结区/执行环/撤离点等）。规划期要用它
    # 估算行为段的全程里程，续航闸门才不会只算"到作业点"那一段。
    behavior: dict = field(default_factory=dict)

    @property
    def remain(self):
        return max(0.0, self.work - self.progress)


@dataclass(frozen=True)
class Command:
    """一条下发指令 = 一台平台对一个作业的一次尝试。

    worker_id 即平台 pid；同一协同作业的多台平台各收到一条指令，
    携带相同的 job_id / attempt 与完整的作业参数。
    """
    command_id: str
    job_id: str
    worker_id: str
    attempt: int
    issued_sim_s: int
    start_sim_s: int            # 计划开工步（含在途时间）
    expected_end_sim_s: int
    action: str = "start"
    target_command_id: Optional[str] = None
    task: dict = field(default_factory=dict)
    delivery: dict = field(default_factory=dict)

    def to_wire(self, run_id, plan_id):
        return dict(protocol=PROTOCOL_V2, run_id=run_id, plan_id=plan_id,
                    clock="demo_sim_steps", command=self._as_public())

    def _as_public(self):
        return dict(command_id=self.command_id, job_id=self.job_id,
                    worker_id=self.worker_id, attempt=self.attempt,
                    issued_sim_s=self.issued_sim_s,
                    start_sim_s=self.start_sim_s,
                    expected_end_sim_s=self.expected_end_sim_s,
                    action=self.action,
                    target_command_id=self.target_command_id,
                    task=self.task, delivery=self.delivery)


def task_block(job: Job, members: List[str], now: int) -> dict:
    """指令里的作业参数块：下层凭这一块就能独立执行，不依赖中间层对象。

    goal 是目标位姿（x/y/z/yaw），供下层的运动控制器（motion.GoalController）
    把"去作业点"翻译成逐拍 Twist。yaw 缺省 0（无朝向要求）；z 用作业的
    altitude（>0 时只有空中平台能接，见能力闸门）。position 仍保留
    为二维作业点，供规划/报告使用，与 goal 的 x/y 一致。
    """
    return dict(job_id=job.job_id, jtype=job.jtype,
                position=[job.pos[0], job.pos[1]], altitude=job.altitude,
                goal=dict(x=job.pos[0], y=job.pos[1], z=job.altitude, yaw=0.0),
                work=job.work, window=[job.window[0], job.window[1]],
                crew=job.crew, members=list(members),
                # 融合层计划给出的角色（边界段/门哨/机动组）；基座场景没有
                # 该字段时为 {}，行为层自行按几何分工。
                roles=dict(getattr(job, "_interop_roles", {}) or {}),
                window_deadline=job.window[1])


def delivery_block(p: Platform) -> dict:
    """投递信息：对齐下游真实话题。发令纪律见 reporting/文档：
    单一持续发令源、停止须显式全零、约 20 Hz 发令频率。
    pos/battery 是发令时刻的平台状态快照（下层本应自己掌握，
    演示替身用快照初始化，之后由替身自行推进）。

    运动字段（为对接真实运动控制器而补，见 motion.py）：
      motion_caps   平台运动能力上限（线速度/角速度/可爬升），
                    供下层 GoalController 构造增益，与规划 travel 同源
      goal_pose     目标位姿（x/y/z/yaw）——由指令的 task.position /
                    altitude 与平台当前位置推导，本函数只填平台快照，
                    目标位姿在 coordinator 组装时用 task_block 的
                    position + altitude 明确，见 task_block 的 goal 字段。
    """
    return dict(robot_no=p.robot_no, kind=p.kind,
                cmd_vel_topic=p.topic, pose_topic=p.pos_topic,
                can_climb=p.can_climb,
                pos=[p.pos[0], p.pos[1]], battery=p.battery,
                speed=p.speed, work_rate=p.work_rate,
                payload=p.payload, sensor=p.sensor,
                move_cost=p.move_cost, work_cost=p.work_cost,
                ammo=p.ammo,
                motion_caps=dict(max_linear=p.speed, max_angular=0.5,
                                 tol_pos=0.5, tol_yaw=0.15,
                                 can_climb=p.can_climb),
                stop_rule="explicit_zero_twist",
                note="cmd_vel 只接受速度级指令；目标点闭环控制属于本层适配")


# ------------------------------------------------------------------
# 场景校验（v2）
# ------------------------------------------------------------------
_SCENARIO_TUNING = {"H", "K", "dev_threshold", "grace_s", "max_attempts",
                    "objective", "max_ticks", "timeline", "rules"}
_OBJECTIVES = ("makespan", "dispersion", "energy")

# ------------------------------------------------------------------
# timeline（实验事件时间线）——数据驱动的导调事件，减少改演示脚本的需要
#
# 每个事件 = {t, event, ...}，t 为绝对仿真步（>=0）。
#   member_lost   {t, event, robot_no}            第 t 步该平台失联
#   job_fail      {t, event, job_id}              第 t 步该作业任务级失败
#   job_delay     {t, event, job_id, delay}       第 t 步该作业在途延迟 delay 步
#   job_slow      {t, event, job_id, factor}      第 t 步该作业进度按 factor 打折
#
# 触发语义：
#   * member_lost 在 now == t 时立即失联（全局事件，与作业是否在途无关）。
#   * job_* 事件在 now >= t 且目标作业**已在途**时触发；若 t 时刻作业
#     尚未下发，事件等待作业在途后立即触发（"让作业失败"必须等作业先
#     开始，不能因 t 设早了而静默丢失）。
#
# 约束（check_scenario_v2 强制）：
#   * event 必须是上表之一；字段多余/缺失/类型错都拒绝
#   * t 必须是非负整数；robot_no / job_id 必须能指到场景里的实体
#   * 事件按 t 升序执行；同一步多个事件全部执行（不互相吞掉）
#   * 事件只描述"何时做什么"，不描述"如何校验"——约束检查仍由代码执行
# ------------------------------------------------------------------
TIMELINE_EVENTS = {
    "member_lost": {"required": ("robot_no",), "optional": ()},
    "job_fail":    {"required": ("job_id",), "optional": ()},
    "job_delay":   {"required": ("job_id", "delay"), "optional": ()},
    "job_slow":    {"required": ("job_id", "factor"), "optional": ()},
}

# ------------------------------------------------------------------
# rules（规则可配置参数）——只开放"明确需要配置的参数"，不开放"检查开关"
#
# 白名单里只有阈值/容忍量这类参数。能力约束检查（续航/载荷/高度/传感器/
# 运动性能）由 planner_v2.feasible 代码执行，**不能通过场景关闭或开关**。
# check_scenario_v2 会拒绝任何试图开关/关闭检查的字段（见下）。
# ------------------------------------------------------------------
_RULE_PARAMS = {"dev_threshold", "grace_s", "max_attempts"}
# 这些词一旦出现在 rules 键里就拒绝：它们意味着"想开关约束检查"
_RULE_FORBIDDEN_HINTS = ("check", "enable", "disable", "enabled", "disabled",
                         "switch", "skip", "bypass", "ignore")


def _validate_timeline(timeline, known_robots, known_jobs):
    """校验 timeline 数组。返回规范化后的排序列表。"""
    if timeline is None:
        return []
    if not isinstance(timeline, list):
        raise ValueError("timeline 必须是数组")
    out = []
    for idx, item in enumerate(timeline):
        if not isinstance(item, dict):
            raise ValueError("timeline[%d] 必须是对象" % idx)
        event = item.get("event")
        if event not in TIMELINE_EVENTS:
            raise ValueError("timeline[%d] 未知事件 %r（可选 %s）"
                             % (idx, event, "/".join(sorted(TIMELINE_EVENTS))))
        spec = TIMELINE_EVENTS[event]
        allowed = set(spec["required"]) | set(spec["optional"]) | {"t", "event"}
        unknown = _non_meta_keys(set(item)) - allowed
        if unknown:
            raise ValueError("timeline[%d] 事件 %s 含未约定字段 %s"
                             % (idx, event, sorted(unknown)))
        t = item.get("t")
        if type(t) is not int or t < 0:
            raise ValueError("timeline[%d] t 必须是非负整数" % idx)
        for key in spec["required"]:
            if key not in item:
                raise ValueError("timeline[%d] 事件 %s 缺少字段 %s"
                                 % (idx, event, key))
        # 实体引用校验
        if "robot_no" in item:
            no = item["robot_no"]
            if no not in known_robots:
                raise ValueError("timeline[%d] robot_no=%r 不在场景 platforms 里"
                                 % (idx, no))
        if "job_id" in item:
            jid = item["job_id"]
            if jid not in known_jobs:
                raise ValueError("timeline[%d] job_id=%r 不在场景 jobs 里"
                                 % (idx, jid))
        # 数值字段类型
        if "delay" in item and (type(item["delay"]) is not int
                                or item["delay"] < 0):
            raise ValueError("timeline[%d] delay 必须是非负整数" % idx)
        if "factor" in item and (type(item["factor"]) not in (int, float)
                                 or not 0 < item["factor"] < 1):
            raise ValueError("timeline[%d] factor 必须是 (0,1) 开区间内的数" % idx)
        out.append(dict(item))
    # 按 t 升序；同 t 保持原始相对顺序（Python 排序稳定，同 t 不吞事件）
    out.sort(key=lambda e: e["t"])
    return out


def _validate_rules(rules):
    """校验 rules 对象。只放白名单参数，拒绝任何开关检查的字段。"""
    if rules is None:
        return {}
    if not isinstance(rules, dict):
        raise ValueError("rules 必须是对象")
    out = {}
    for key, value in rules.items():
        if key not in _RULE_PARAMS:
            lowered = key.lower()
            if any(h in lowered for h in _RULE_FORBIDDEN_HINTS):
                raise ValueError(
                    "rules 不允许字段 %r：约束检查（续航/载荷/高度/传感器/"
                    "运动性能）由代码执行，不能通过场景文件开关或关闭"
                    % key)
            raise ValueError("rules 只允许配置 %s，收到未约定字段 %r"
                             % (sorted(_RULE_PARAMS), key))
        # 类型与范围
        if key == "max_attempts":
            if type(value) is not int or value < 1:
                raise ValueError("rules.max_attempts 必须是正整数")
        else:  # dev_threshold / grace_s
            if type(value) not in (int, float) or value < 0:
                raise ValueError("rules.%s 必须是非负数" % key)
        out[key] = value
    return out


def _non_meta_keys(keys):
    """场景对象里以 _ 开头的字段是追溯/文档元数据（来源坐标、地标等），
    不参与规划决策，校验时予以放行。"""
    return {k for k in keys if not (isinstance(k, str) and k.startswith("_"))}


def check_scenario_v2(data):
    """校验 v2 场景 JSON。只验输入，不注入运行状态。"""
    if not isinstance(data, dict):
        raise ValueError("场景必须是 JSON 对象")
    if data.get("protocol") != PROTOCOL_V2:
        raise ValueError("不支持的 protocol（应为 %s）" % PROTOCOL_V2)
    objective = data.get("objective", "makespan")
    if objective not in _OBJECTIVES:
        raise ValueError("objective 必须是 %s 之一" % ("/".join(_OBJECTIVES)))
    for key in ("H", "K", "max_attempts"):
        v = data.get(key)
        if v is not None and (type(v) is not int or v < 1):
            raise ValueError("%s 必须是正整数" % key)
    for key in ("dev_threshold", "grace_s"):
        v = data.get(key)
        if v is not None and (type(v) not in (int, float) or v < 0):
            raise ValueError("%s 必须是非负数" % key)

    # rules 段（可配置参数白名单 + 拒绝开关检查字段）
    if "rules" in data:
        _validate_rules(data["rules"])

    platforms = data.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        raise ValueError("platforms 必须是非空列表")
    seen_no = set()
    for item in platforms:
        if not isinstance(item, dict):
            raise ValueError("platform 必须是对象")
        if _non_meta_keys(set(item)) - {"robot_no", "pos"}:
            raise ValueError("platform 只允许 robot_no 和 pos（能力参数由编成层给出，"
                             "不能在场景里私自改写）")
        no = item.get("robot_no")
        if type(no) is not int or not 1 <= no <= fleet.FLEET_SIZE:
            raise ValueError("robot_no 必须是 1-%d 的整数" % fleet.FLEET_SIZE)
        if no in seen_no:
            raise ValueError("robot_no 重复：%d" % no)
        seen_no.add(no)
        pos = item.get("pos", None)
        if pos is not None:
            if (not isinstance(pos, list) or len(pos) != 2
                    or any(type(v) not in (int, float) for v in pos)):
                raise ValueError("pos 必须是 [x, y] 数值对")

    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("jobs 必须是非空列表")
    seen_job = set()
    allowed_job_keys = {"job_id", "type", "pos"} | set(JOB_SPECS["patrol"])
    for item in jobs:
        if not isinstance(item, dict):
            raise ValueError("job 必须是对象")
        if _non_meta_keys(set(item)) - allowed_job_keys - {"window"}:
            raise ValueError("job 含未约定字段（允许 job_id/type/pos 或模板参数）")
        job_id = item.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id 必须是非空字符串")
        if job_id in seen_job:
            raise ValueError("job_id 重复")
        seen_job.add(job_id)
        pos = item.get("pos")
        if (not isinstance(pos, list) or len(pos) != 2
                or any(type(v) not in (int, float) for v in pos)):
            raise ValueError("job pos 必须是 [x, y] 数值对")
        if "type" in item:
            if item["type"] not in JOB_SPECS:
                raise ValueError("未知作业类型：%r（可选 %s）"
                                 % (item["type"], "/".join(sorted(JOB_SPECS))))
            unknown = _non_meta_keys(set(item)) - {"job_id", "type", "pos",
                                                   "window", "crew"}
            if unknown:
                raise ValueError("使用 type 模板时不能再覆盖 %s" % sorted(unknown))
            if "window" in item:
                window = item["window"]
                if (not isinstance(window, list) or len(window) != 2
                        or any(type(v) is not int for v in window)
                        or window[0] >= window[1]):
                    raise ValueError("window 必须是 [开始, 截止] 整数对且开始<截止")
            if "crew" in item:
                if type(item["crew"]) is not int or item["crew"] < 1:
                    raise ValueError("crew 必须是正整数")
        else:
            for key in ("work", "crew"):
                if type(item.get(key)) not in (int, float):
                    raise ValueError("job 缺少数值字段 %s" % key)
            if type(item.get("need_payload")) not in (int, float):
                raise ValueError("job 缺少数值字段 need_payload")
            if item.get("need_sensor") is not None and not isinstance(
                    item.get("need_sensor"), str):
                raise ValueError("need_sensor 必须是字符串或 null")
            window = item.get("window")
            if (not isinstance(window, list) or len(window) != 2
                    or any(type(v) is not int for v in window)
                    or window[0] >= window[1]):
                raise ValueError("window 必须是 [开始, 截止] 整数对且开始<截止")

    # timeline 段（导调事件时间线，实体引用须指到上面的 platforms/jobs）
    _validate_timeline(data.get("timeline"), seen_no, seen_job)


def resolve_timeline(data):
    """返回规范化（已排序、已校验）的 timeline 列表。无 timeline 返回 []。"""
    robots = {item["robot_no"] for item in data.get("platforms", [])}
    jobs = {item["job_id"] for item in data.get("jobs", [])}
    return _validate_timeline(data.get("timeline"), robots, jobs)


def resolve_rules(data):
    """返回规范化（已校验）的 rules 字典。无 rules 返回 {}。"""
    return _validate_rules(data.get("rules"))


def build_platforms(data) -> List[Platform]:
    """场景 JSON → 平台对象。能力参数一律来自 fleet.PLANNING_PARAMS。"""
    out = []
    for item in data["platforms"]:
        no = item["robot_no"]
        kind = fleet.kind_of(no)
        s = fleet.PLANNING_PARAMS[kind]
        pos = item.get("pos")
        pos = (float(pos[0]), float(pos[1])) if pos else (0.0, 0.0)
        out.append(Platform(
            pid=fleet.pid_of(no), kind=kind, robot_no=no, pos=pos,
            speed=s["speed"], work_rate=s["work_rate"], battery=s["battery"],
            payload=s["payload"], sensor=s["sensor"],
            can_climb=s["can_climb"], move_cost=s["move_cost"],
            work_cost=s["work_cost"], ammo=int(s.get("ammo", 0)),
            pos_topic=fleet.pose_topic_of(no)))
    return out


def build_jobs(data) -> List[Job]:
    """场景 JSON → 作业对象。type 模板优先，否则逐字段。"""
    out = []
    for item in data["jobs"]:
        pos = (float(item["pos"][0]), float(item["pos"][1]))
        if "type" in item:
            s = JOB_SPECS[item["type"]]
            work, window = float(s["work"]), tuple(item.get("window", s["window"]))
            crew = int(item.get("crew", s["crew"]))
            need_payload = float(s["need_payload"])
            need_sensor, altitude = s["need_sensor"], float(s.get("altitude", 0))
            jtype = item["type"]
        else:
            work = float(item["work"])
            window = tuple(item["window"])
            crew = int(item["crew"])
            need_payload = float(item["need_payload"])
            need_sensor = item.get("need_sensor")
            altitude = float(item.get("altitude", 0))
            # 4.1 运行视图：job 不带 "type" 模板，只带 _task_type；
            # 派生出可被行为层识别的 jtype，未知任务仍记 custom。
            jtype = TASK_TYPE_TO_JOB.get(str(item.get("_task_type") or ""),
                                         "custom")
        out.append(Job(job_id=item["job_id"], jtype=jtype, pos=pos,
                       work=work, window=window, crew=crew,
                       need_payload=need_payload, need_sensor=need_sensor,
                       altitude=altitude,
                       behavior=dict(item.get("_behavior") or {})))
    return out
