# -*- coding: utf-8 -*-
"""
contract.py —— 接口契约层

这一层只做一件事：定义"数据长什么样"。不含任何算法。
真实接口到了之后，只需要重写 from_upstream() 这一个函数，
planner.py / executor.py / run_flow.py 都不用动。

每个字段的单位写在注释里。单位不写清楚，后面所有阈值都会算错。
"""

import json
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------
# 平台能力参数（公开值，可配置；进入甲方环境后换成实际值）
#   speed      移动速度（距离单位/步）
#   work_rate  作业效率（工作量单位/步）
#   battery    续航（电量单位；**不是步数**）
#   payload    载荷
#   sensor     传感器类型
#   move_cost  移动一步的耗电（电量/步）——【我方暂定】
#   work_cost  作业一步的耗电（电量/步）——【我方暂定】
#
# 能耗模型（我方暂定，WP1 引入）：
#     一次指派的预计耗电 = 移动步数 × move_cost + 作业步数 × work_cost
#
# 这两个系数怎么定的（关键，别再改回"快的更省"）：
#   第一版我把"跑得快的平台"定成"更省电"，结果 energy 目标和 makespan 目标
#   永远选同一台平台——实测 seed0 两个目标成绩单**一模一样**，区分度为零。
#   物理上这是反的：功率随速度上升（阻力 ~ v^2）、随作业吞吐上升。
#   所以改为：
#       move_cost = MOVE_K × speed^2        （MOVE_K = 0.5，我方暂定）
#       work_cost = WORK_K × work_rate^2    （WORK_K = 1.0，我方暂定）
#   于是"移动能耗 = MOVE_K × 距离 × speed"，"作业能耗 = WORK_K × 工作量 × work_rate"
#   ——跑得快的更费电、干得快的也更费电，与完工时间天然反向，
#   两个目标才会选出不同的平台。
#
# 注意 move_cost 可以 > 1：续航闸门按**电量**算，不是按步数算。
# 真实数据到了只需改下面 8 个数，planner / executor 都不用动。
# ------------------------------------------------------------------
_MOVE_K = 0.5        # 我方暂定：移动功率系数
_WORK_K = 1.0        # 我方暂定：作业功率系数
PLATFORM_SPECS = {
    "tank":  dict(speed=1.0, work_rate=1.2, battery=120.0, payload=8.0, sensor="eo",
                  move_cost=round(_MOVE_K * 1.0 ** 2, 3),
                  work_cost=round(_WORK_K * 1.2 ** 2, 3)),
    "ugv":   dict(speed=0.8, work_rate=1.0, battery=100.0, payload=6.0, sensor="eo",
                  move_cost=round(_MOVE_K * 0.8 ** 2, 3),
                  work_cost=round(_WORK_K * 1.0 ** 2, 3)),
    "uav_a": dict(speed=2.0, work_rate=0.6, battery=60.0,  payload=2.0, sensor="sar",
                  move_cost=round(_MOVE_K * 2.0 ** 2, 3),
                  work_cost=round(_WORK_K * 0.6 ** 2, 3)),
    "uav_b": dict(speed=1.6, work_rate=0.5, battery=80.0,  payload=1.5, sensor="ir",
                  move_cost=round(_MOVE_K * 1.6 ** 2, 3),
                  work_cost=round(_WORK_K * 0.5 ** 2, 3)),
}

# ------------------------------------------------------------------
# 作业类型模板（配置化：新增/修改作业类型只改这里，不改代码）
#   work         完成所需工作量
#   window       允许的时间窗 [最早开始, 最晚结束]，单位：步
#   crew         需要几台平台协同
#   need_payload 所需载荷
#   need_sensor  所需传感器，None 表示不挑
# ------------------------------------------------------------------
TASK_SPECS = {
    "patrol":   dict(work=12.0, window=(0, 60), crew=1, need_payload=0.0, need_sensor="eo"),
    "blockade": dict(work=18.0, window=(0, 80), crew=3, need_payload=2.0, need_sensor=None),
    "recon":    dict(work=10.0, window=(0, 50), crew=2, need_payload=0.0, need_sensor="sar"),
    "assault":  dict(work=20.0, window=(0, 90), crew=4, need_payload=4.0, need_sensor=None),
    "hold":     dict(work=15.0, window=(0, 70), crew=2, need_payload=1.0, need_sensor="eo"),
}

OBJECTIVES = ("makespan", "dispersion", "energy")


def dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class Platform:
    pid: str
    ptype: str
    pos: Tuple[float, float]
    battery: float          # 剩余续航（步）
    payload: float          # 剩余载荷
    speed: float
    work_rate: float
    sensor: str
    alive: bool = True
    # 能耗系数（我方暂定）。给默认值的目的：老的场景 JSON 与单测里的
    # BASE_P 不带这两个字段也能构造成功，不会为了让模型跑起来而全量改测试。
    move_cost: float = 1.0
    work_cost: float = 1.0


@dataclass
class Task:
    tid: str
    ttype: str
    pos: Tuple[float, float]
    work: float             # 总工作量
    window: Tuple[int, int]
    crew: int
    need_payload: float
    need_sensor: Optional[str]
    progress: float = 0.0   # 已完成工作量
    status: str = "open"    # open / running / done / failed


@dataclass
class GroupSnapshot:
    """上层编组送下来的一次快照。真实接口到了只改 from_upstream()。"""
    version: int            # 编组版本号：变了就说明成员或关系变了
    step: int
    objective: str
    platforms: List[Platform]
    tasks: List[Task]


@dataclass
class Assignment:
    """2.2（2）要求的四类输出，全在这里。"""
    tid: str
    pids: List[str]
    start: int              # 任务时序：开始步
    end: int                # 时间窗口：结束步
    seq: int                # 时序序号
    coord: str = ""         # 协同约束，如 "crew>=3"


@dataclass
class Plan:
    plan_id: int
    created_at: int
    horizon: int            # H：这份计划向前覆盖多少步
    group_version: int
    rule_version: str
    objective: str
    assignments: List[Assignment]
    rejected: List[Dict] = field(default_factory=list)   # 没派出去的作业及原因


@dataclass
class Feedback:
    """下层单平台回传的一次反馈。真实下层到位后由真实模块产生。"""
    pid: str
    tid: Optional[str]
    step: int
    progress: float
    status: str             # running / done / failed / idle
    battery: float
    pos: Tuple[float, float]


def sample_scenario(seed: int = 0,
                    n_platforms: int = 15,
                    n_tasks: int = 8,
                    objective: str = "makespan",
                    step: int = 0,
                    version: int = 1,
                    work_scale: float = 1.0) -> GroupSnapshot:
    """替身：上层编组还没接上时，自己造一份快照。

    work_scale：整体放大作业量，用来调节「资源紧张程度」。
    默认 1.0（不改变任何已有结果）。

    为什么要这个参数：默认场景下 15 台 × 40 步有约 600 人步可用，
    而作业只需求约 58 人步——过剩 10 倍，随机策略就能 100% 完成，
    好坏策略看不出差别。实测随机完成率随 work_scale 变化：
        1 → 100%   3 → 54.7%   5 → 35.9%   8 → 7.8%   12 → 0%
    work_scale=5 时随机基线约 36%，与 taskalloc（旧环境）的 0.3542 基本持平，
    便于跨环境对照。规则基线与学习层必须用同一个值，否则对照不成立。
    """
    rng = random.Random(seed)
    ptypes = list(PLATFORM_SPECS.keys())
    platforms = []
    for i in range(n_platforms):
        t = ptypes[i % len(ptypes)]
        s = PLATFORM_SPECS[t]
        platforms.append(Platform(
            pid="P%02d" % i, ptype=t,
            pos=(round(rng.uniform(0, 100), 2), round(rng.uniform(0, 100), 2)),
            battery=float(s["battery"]), payload=float(s["payload"]),
            speed=s["speed"], work_rate=s["work_rate"], sensor=s["sensor"],
            move_cost=float(s["move_cost"]), work_cost=float(s["work_cost"]),
        ))
    ttypes = list(TASK_SPECS.keys())
    tasks = []
    for j in range(n_tasks):
        tt = ttypes[j % len(ttypes)]
        s = TASK_SPECS[tt]
        tasks.append(Task(
            tid="T%02d" % j, ttype=tt,
            pos=(round(rng.uniform(0, 100), 2), round(rng.uniform(0, 100), 2)),
            work=float(s["work"]) * work_scale, window=tuple(s["window"]), crew=int(s["crew"]),
            need_payload=float(s["need_payload"]), need_sensor=s["need_sensor"],
        ))
    return GroupSnapshot(version=version, step=step, objective=objective,
                         platforms=platforms, tasks=tasks)


# ------------------------------------------------------------------
# 场景文件读写
#
# 真实接口到了，只需要让上层把它的输出转成下面这个 JSON，
# 或者改 from_upstream() 直接解析它的原生格式。
# planner / executor / run_flow 都不用动。
# ------------------------------------------------------------------

def save_scenario(snap: GroupSnapshot, path: str) -> None:
    """把一次快照写成 JSON 文件。"""
    data = {
        "format": "taskalloc-scenario/v1",
        "version": snap.version,
        "step": snap.step,
        "objective": snap.objective,
        "platforms": [
            dict(pid=p.pid, ptype=p.ptype, pos=list(p.pos), battery=p.battery,
                 payload=p.payload, speed=p.speed, work_rate=p.work_rate,
                 sensor=p.sensor, alive=p.alive,
                 move_cost=p.move_cost, work_cost=p.work_cost)
            for p in snap.platforms
        ],
        "tasks": [
            dict(tid=t.tid, ttype=t.ttype, pos=list(t.pos), work=t.work,
                 window=list(t.window), crew=t.crew,
                 need_payload=t.need_payload, need_sensor=t.need_sensor,
                 progress=t.progress, status=t.status)
            for t in snap.tasks
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_scenario(path: str) -> GroupSnapshot:
    """从 JSON 文件读出一次快照。

    这是 WP0 的验收点：换场景只换文件，不改代码。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") != "taskalloc-scenario/v1":
        raise ValueError("格式标识不是 taskalloc-scenario/v1：%r" % data.get("format"))

    platforms = [Platform(
        pid=p["pid"], ptype=p["ptype"], pos=tuple(p["pos"]),
        battery=p["battery"], payload=p["payload"], speed=p["speed"],
        work_rate=p["work_rate"], sensor=p["sensor"],
        alive=p.get("alive", True),
        move_cost=p.get("move_cost", 1.0), work_cost=p.get("work_cost", 1.0))
        for p in data["platforms"]]

    tasks = [Task(
        tid=t["tid"], ttype=t["ttype"], pos=tuple(t["pos"]), work=t["work"],
        window=tuple(t["window"]), crew=t["crew"],
        need_payload=t["need_payload"], need_sensor=t["need_sensor"],
        progress=t.get("progress", 0.0), status=t.get("status", "open"))
        for t in data["tasks"]]

    return GroupSnapshot(version=data["version"], step=data.get("step", 0),
                         objective=data["objective"],
                         platforms=platforms, tasks=tasks)
