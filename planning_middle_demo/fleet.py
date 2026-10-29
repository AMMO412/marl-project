# -*- coding: utf-8 -*-
"""
fleet.py —— 下游编成与平台参数层（v2）

事实来源（均已在《机器人移动话题说明.md》核对）：
  * 下游 GazeboUEBridge 场景固定 50 台、四类、按号段划分：
      01–20 UGV（差速）  21–30 TANK（履带外观+差速代理）
      31–40 PLANE（关重力速度代理）  41–50 WING（同 PLANE）
  * 每台一个 `/rover_XX/cmd_vel`（geometry_msgs/msg/Twist），
    位姿在 `/model/rover_XX/pose`。编号不足两位补零。
  * 只有 31–50 支持 linear.z（升降）；地面平台 z 恒为 0。
  * Twist 不含目标/时长/电量；停止必须显式发全零（无超时自动停车）。

本文件登记两套**互不混用**的数值：
  1. PLANNING_PARAMS —— 规划用的能力参数（我方暂定，场景单位）。
     下游真实最大速度/载荷/续航均未知（见《四类平台参数指标与Gazebo实现
     详尽调研》第 10 节：当前能登记的事实只有四类、编号、话题和控制方式），
     所以这里全部标注为暂定值，真实数据到位只改这一张表。
  2. load_references() —— 公开参考资料登记（config/platform_references.json，
     厂家/公开模型口径，m/s、kg、s），只用于报告展示，不参与规划决策。

单位口径（别混）：
  规划侧   场景坐标无量纲（100×100），速度=场景单位/步，电量=电量单位
  参考侧   米、秒、千克
  两套单位之间**没有换算关系**，不许拿 Husky 的 1 m/s 去改 speed=0.8。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ------------------------------------------------------------------
# 下游编成（事实，来自说明第 1 节）
# ------------------------------------------------------------------
FLEET_RANGES = [
    ("UGV", 1, 20),
    ("TANK", 21, 30),
    ("PLANE", 31, 40),
    ("WING", 41, 50),
]
FLEET_SIZE = 50
CLIMB_KINDS = {"PLANE", "WING"}          # 只有两类飞机支持 linear.z


def kind_of(robot_no):
    """机器人编号 → 四类之一。"""
    if type(robot_no) is not int or not 1 <= robot_no <= FLEET_SIZE:
        raise ValueError("机器人编号应在 1-%d 之间：%r" % (FLEET_SIZE, robot_no))
    for kind, lo, hi in FLEET_RANGES:
        if lo <= robot_no <= hi:
            return kind
    raise ValueError("unreachable")


def topic_of(robot_no):
    """编号 → cmd_vel 话题名（每台一个，不是广播）。"""
    return "/rover_%02d/cmd_vel" % robot_no


def pose_topic_of(robot_no):
    """编号 → 位姿话题名（Gazebo → ROS 2 → UE，只读）。"""
    return "/model/rover_%02d/pose" % robot_no


def build_roster():
    """生成 50 台编成表。字段与下游 fleet-roster.json 对齐。"""
    roster = []
    for kind, lo, hi in FLEET_RANGES:
        for no in range(lo, hi + 1):
            roster.append(dict(no=no, kind=kind,
                               topic=topic_of(no),
                               pose_topic=pose_topic_of(no),
                               can_climb=(kind in CLIMB_KINDS)))
    return roster


def pid_of(robot_no):
    """编号 → 本层平台 ID。与话题一一对应，不做任何算术映射。"""
    return "rover_%02d" % robot_no


# ------------------------------------------------------------------
# 规划参数（我方暂定；场景单位；真实值到位只改这张表）
#
#   speed      移动速度（场景单位/步）
#   work_rate  作业效率（工作量单位/步）
#   battery    续航（电量单位，不是步数）
#   payload    载荷（场景单位）
#   sensor     传感器类别（eo / sar / ir）
#   move_cost  移动一步耗电 —— MOVE_K * speed^2（我方暂定）
#   work_cost  作业一步耗电 —— WORK_K * work_rate^2（我方暂定）
#
# 能耗系数的来历（照抄 planning/ 的教训，别改回"快的更省"）：
#   第一版把 move_cost 定成与速度反相关，结果 energy 目标与 makespan
#   永远选同一台平台，区分度为零。物理上功率随速度上升，所以取
#   move_cost = 0.5*speed^2、work_cost = 1.0*work_rate^2。
# ------------------------------------------------------------------
_MOVE_K = 0.5
_WORK_K = 1.0
PLANNING_PARAMS = {
    "UGV":   dict(speed=0.8, work_rate=1.0, battery=100.0, payload=6.0,
                  sensor="eo", can_climb=False,
                  move_cost=round(_MOVE_K * 0.8 ** 2, 3),
                  work_cost=round(_WORK_K * 1.0 ** 2, 3)),
    "TANK":  dict(speed=1.0, work_rate=1.2, battery=120.0, payload=8.0,
                  sensor="eo", can_climb=False,
                  move_cost=round(_MOVE_K * 1.0 ** 2, 3),
                  work_cost=round(_WORK_K * 1.2 ** 2, 3)),
    "PLANE": dict(speed=2.0, work_rate=0.6, battery=60.0, payload=2.0,
                  sensor="sar", can_climb=True,
                  move_cost=round(_MOVE_K * 2.0 ** 2, 3),
                  work_cost=round(_WORK_K * 0.6 ** 2, 3)),
    "WING":  dict(speed=1.6, work_rate=0.5, battery=80.0, payload=1.5,
                  sensor="ir", can_climb=True,
                  move_cost=round(_MOVE_K * 1.6 ** 2, 3),
                  work_cost=round(_WORK_K * 0.5 ** 2, 3)),
}


# ------------------------------------------------------------------
# 公开参考参数登记（只展示、不参与决策）
# ------------------------------------------------------------------
def load_references():
    """读取 config/platform_references.json；读不到返回 None，不抛错。"""
    path = ROOT / "config" / "platform_references.json"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        return None


if __name__ == "__main__":
    roster = build_roster()
    assert len(roster) == 50
    assert roster[0]["kind"] == "UGV" and roster[0]["topic"] == "/rover_01/cmd_vel"
    assert roster[20]["kind"] == "TANK" and roster[20]["pose_topic"] == "/model/rover_21/pose"
    assert roster[30]["kind"] == "PLANE" and roster[30]["can_climb"]
    assert roster[49]["kind"] == "WING" and not roster[10]["can_climb"]
    assert kind_of(1) == "UGV" and kind_of(21) == "TANK"
    assert kind_of(31) == "PLANE" and kind_of(41) == "WING"
    assert pid_of(7) == "rover_07"
    for kind in ("UGV", "TANK", "PLANE", "WING"):
        p = PLANNING_PARAMS[kind]
        assert p["speed"] > 0 and p["battery"] > 0 and p["work_rate"] > 0
    refs = load_references()
    assert refs is None or set(refs["profiles"]) == {"UGV", "TANK", "PLANE", "WING"}
    print("fleet.py 自测通过：50 台编成、四类规划参数、参考登记均可读")
