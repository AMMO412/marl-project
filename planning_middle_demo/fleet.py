# -*- coding: utf-8 -*-
"""
fleet.py —— 下游编成与平台参数层（v2）

事实来源（均已在《机器人移动话题说明.md》核对）：
  * 下游 GazeboUEBridge 场景固定 50 台、四类、按号段划分：
      01–20 UGV（差速）  21–30 TANK（履带外观+差速代理）
      31–40 PLANE（关重力速度代理）  41–50 WING（同 PLANE）
  * 每台一个 `/container_00/robot_XXX` 移动话题（geometry_msgs/msg/Twist，
    三位编号；旧版 `/rover_XX/cmd_vel` 已停用），位姿在
    `/model/robot_XXX/pose`。容器名/位姿前缀/话题后缀可用环境变量覆盖：
    `FLEET_CONTAINER_NAME`、`FLEET_POSE_PREFIX`、`FLEET_CMD_SUFFIX`。
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
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 下游 ROS 2 命名（2026-10-30 变更）：容器命名空间 + 三位机器人编号。
# 例：/container_00/robot_041；位姿 /model/robot_041/pose。
# 用环境变量覆盖时不需要改代码：
#   FLEET_CONTAINER_NAME=container_00
#   FLEET_POSE_PREFIX=/model
#   FLEET_CMD_SUFFIX=            （若桥接话题仍带 /cmd_vel，则设为 /cmd_vel）
CONTAINER_NAME = os.environ.get("FLEET_CONTAINER_NAME", "container_00")
POSE_PREFIX = os.environ.get("FLEET_POSE_PREFIX", "/model").rstrip("/")
CMD_SUFFIX = os.environ.get("FLEET_CMD_SUFFIX", "")
# 桥接命名不一致时的最后手段：整条话题模板，占位符 {robot} 如 robot_041、
# {no} 如 41、{container} 如 container_00。例如旧 bridge 用
#   FLEET_CMD_TOPIC_TEMPLATE=/robot_{robot_no:03d}/cmd_vel
CMD_TOPIC_TEMPLATE = os.environ.get("FLEET_CMD_TOPIC_TEMPLATE", "")
POSE_TOPIC_TEMPLATE = os.environ.get("FLEET_POSE_TOPIC_TEMPLATE", "")

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


def robot_name(robot_no):
    """编号 → Gazebo/桥接里的机器人模型名：robot_001。"""
    return "robot_%03d" % int(robot_no)


def _format_template(template, robot_no):
    return template.format(robot=robot_name(robot_no),
                           robot_no=int(robot_no), no=int(robot_no),
                           container=CONTAINER_NAME)


def topic_of(robot_no):
    """编号 → 移动话题名（每台一个，不是广播）。

    2026-10-30 起为 `/container_00/robot_001`；不再带 `/rover_XX/cmd_vel`
    的旧前缀。桥接命名不一致时用 FLEET_CMD_TOPIC_TEMPLATE 显式指定整条
    话题（占位符 robot/robot_no/no/container），不在代码里猜。
    """
    if CMD_TOPIC_TEMPLATE:
        return _format_template(CMD_TOPIC_TEMPLATE, robot_no)
    return "/%s/%s%s" % (CONTAINER_NAME, robot_name(robot_no), CMD_SUFFIX)


def pose_topic_of(robot_no):
    """编号 → 位姿话题名（Gazebo → ROS 2 → UE，只读）。"""
    if POSE_TOPIC_TEMPLATE:
        return _format_template(POSE_TOPIC_TEMPLATE, robot_no)
    return "%s/%s/pose" % (POSE_PREFIX, robot_name(robot_no))


def build_roster():
    """生成 50 台编成表。字段与下游 fleet-roster.json 对齐。"""
    roster = []
    for kind, lo, hi in FLEET_RANGES:
        for no in range(lo, hi + 1):
            roster.append(dict(no=no, kind=kind, name=robot_name(no),
                               topic=topic_of(no),
                               pose_topic=pose_topic_of(no),
                               can_climb=(kind in CLIMB_KINDS)))
    return roster


def pid_of(robot_no):
    """编号 → 本层内部平台 ID（rover_XX）。

    这是规划/反馈/工作台内部标识，**不是 ROS 话题名**；对下游发布时一律
    用 ``topic_of``。保留旧格式是为了不打断已有反馈日志与工作台记录。
    """
    return "rover_%02d" % robot_no


# ------------------------------------------------------------------
# 规划参数（我方暂定；场景单位；真实值到位只改这张表）
#
#   speed      移动速度（场景单位/步）
#   work_rate  作业效率（工作量单位/步）
#   battery    续航（电量单位，不是步数）
#   payload    载荷（场景单位）
#   sensor     传感器类别（eo / sar / ir）
#   ammo       弹药基数（发）——T-ASL 毁伤/压制的齐射消耗上限（暂定值）
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
                  sensor="eo", can_climb=False, ammo=6,
                  move_cost=round(_MOVE_K * 0.8 ** 2, 3),
                  work_cost=round(_WORK_K * 1.0 ** 2, 3)),
    "TANK":  dict(speed=1.0, work_rate=1.2, battery=120.0, payload=8.0,
                  sensor="eo", can_climb=False, ammo=8,
                  move_cost=round(_MOVE_K * 1.0 ** 2, 3),
                  work_cost=round(_WORK_K * 1.2 ** 2, 3)),
    "PLANE": dict(speed=2.0, work_rate=0.6, battery=320.0, payload=2.0,
                  sensor="sar", can_climb=True, ammo=2,
                  move_cost=round(_MOVE_K * 2.0 ** 2, 3),
                  work_cost=round(_WORK_K * 0.6 ** 2, 3)),
    "WING":  dict(speed=1.6, work_rate=0.5, battery=280.0, payload=1.5,
                  sensor="ir", can_climb=True, ammo=2,
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
    assert roster[0]["kind"] == "UGV" and roster[0]["name"] == "robot_001"
    assert roster[0]["topic"] == "/container_00/robot_001"
    assert roster[20]["kind"] == "TANK" and roster[20]["pose_topic"] == "/model/robot_021/pose"
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
