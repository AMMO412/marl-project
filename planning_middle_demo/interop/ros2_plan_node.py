#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立 ROS 2 速度发布节点，也可用 --dry-run 离线检查。

默认播放同目录 motion_commands.json，其次读取 plan.json。
可选的闭环速度修正由调用方提供，命令行默认只按时间发布。
"""

import argparse
from bisect import bisect_right
import json
import math
from pathlib import Path
import signal
import time


ZERO = (0.0,) * 6


def finite_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("时间和速度必须是有限数值")
    return number


class PlanSchedule:
    """同一话题按开始时间切换，新指令覆盖旧指令，空档输出零速度。"""

    def __init__(self, plan, time_scale=1.0):
        time_scale = finite_number(time_scale)
        if time_scale <= 0:
            raise ValueError("time-scale 必须大于零")
        self.rows = {}
        self.references = {}
        self.source = plan.get("format", "plan")
        self.time_scale = time_scale
        self.full_motion = self.source == "workbench-motion-replay/v1"
        self.platforms = ({row["topic"]: row for row in plan["platforms"]}
                          if self.full_motion else {})
        if self.full_motion and plan.get("velocity_frame") != "body":
            raise ValueError("完整运动指令须使用机体坐标系")
        self.duration = 0.0
        self.boundaries = {0.0}
        self.command_count = 0
        for command in plan["commands"]:
            topic = command["topic"]
            if not isinstance(topic, str) or not topic.startswith("/"):
                raise ValueError("指令 topic 必须是绝对 ROS 2 话题名")
            at_s = finite_number(command.get("at_s", 0.0))
            duration_s = finite_number(command["duration_s"])
            if at_s < 0 or duration_s < 0:
                raise ValueError("at_s 和 duration_s 必须大于或等于零")
            start = finite_number(at_s * time_scale)
            twist = command["twist"]
            values = tuple(finite_number(finite_number(twist.get(group, {}).get(axis, 0.0)) / time_scale)
                           for group in ("linear", "angular") for axis in "xyz")
            end_s = round(at_s + duration_s, 6) if self.full_motion else at_s + duration_s
            end = finite_number(end_s * time_scale)
            self.rows.setdefault(topic, []).append((start, end, values))
            self.references.setdefault(topic, []).append((start, command))
            self.duration = max(self.duration, end)
            self.boundaries.update((start, end))
            self.command_count += 1
        self.starts = {}
        for topic, rows in self.rows.items():
            # 稳定排序使同一时刻的后一条指令生效，包括显式 STOP。
            rows.sort(key=lambda row: row[0])
            self.references[topic].sort(key=lambda row: row[0])
            self.starts[topic] = [row[0] for row in rows]
            if self.full_motion and any(a[1] > b[0] + 1e-7 for a, b in zip(rows, rows[1:])):
                raise ValueError("完整运动指令在同一话题有重叠时段 %s" % topic)

    def velocities_at(self, elapsed):
        velocities = {}
        for topic, rows in self.rows.items():
            index = bisect_right(self.starts[topic], elapsed) - 1
            values = ZERO
            if index >= 0 and elapsed < rows[index][1]:
                values = rows[index][2]
            velocities[topic] = values
        return velocities

    def reference_at(self, topic, elapsed):
        """Return the active reference interval for a future pose controller."""
        if topic not in self.starts:
            return None
        index = bisect_right(self.starts[topic], elapsed) - 1
        if index < 0 or elapsed >= self.rows[topic][index][1]:
            return None
        return self.references[topic][index][1]


def dry_run(schedule):
    print(json.dumps(dict(mode="dry_run", commands=schedule.command_count,
                          topics=list(schedule.rows), duration_s=schedule.duration,
                          source=schedule.source, time_scale=schedule.time_scale),
                     ensure_ascii=False))
    previous = None
    for elapsed in sorted(schedule.boundaries):
        velocities = schedule.velocities_at(elapsed)
        if velocities != previous:
            print(json.dumps(dict(at_s=elapsed, velocities=velocities),
                             ensure_ascii=False))
            previous = velocities


def run_ros(schedule, rate, start_delay, ros_args, pose_controller=None):
    """An optional controller accepts update_pose(topic, PoseStamped) and
    correct(topic, source_time_s, reference, velocity) -> six velocity values.
    """
    import rclpy
    from geometry_msgs.msg import Twist
    from rclpy.node import Node
    from rclpy.signals import SignalHandlerOptions

    class PlanPublisher(Node):
        def __init__(self):
            super().__init__("fleet_plan_publisher")
            self.publishers_by_topic = {
                topic: self.create_publisher(Twist, topic, 10)
                for topic in schedule.rows
            }
            self.origin_ns = None
            self.pose_subscriptions = []
            if pose_controller is not None:
                from geometry_msgs.msg import PoseStamped
                from rclpy.qos import qos_profile_sensor_data
                for topic, platform in schedule.platforms.items():
                    self.pose_subscriptions.append(self.create_subscription(
                        PoseStamped, platform["pose_topic"],
                        lambda message, cmd_topic=topic: pose_controller.update_pose(cmd_topic, message),
                        qos_profile_sensor_data))
            self.finished = not schedule.rows
            self.timer = self.create_timer(1.0 / rate, self.on_timer)
            self.get_logger().info(
                "Loaded %d commands, %d topics, %.3f s, %.1f Hz"
                % (schedule.command_count, len(schedule.rows), schedule.duration, rate))

        def publish_velocities(self, velocities):
            for topic, values in velocities.items():
                message = Twist()
                message.linear.x, message.linear.y, message.linear.z = values[:3]
                message.angular.x, message.angular.y, message.angular.z = values[3:]
                self.publishers_by_topic[topic].publish(message)

        def stop_all(self):
            self.publish_velocities(dict.fromkeys(schedule.rows, ZERO))

        def on_timer(self):
            now_ns = self.get_clock().now().nanoseconds
            if self.get_parameter("use_sim_time").value and now_ns == 0:
                return  # 等待首帧 /clock，再建立本次计划的相对起点。
            if self.origin_ns is None:
                self.origin_ns = now_ns + round(start_delay * 1e9)
            elapsed = (now_ns - self.origin_ns) / 1e9
            velocities = schedule.velocities_at(elapsed)
            if pose_controller is not None and 0 <= elapsed < schedule.duration:
                for topic, velocity in velocities.items():
                    reference = schedule.reference_at(topic, elapsed)
                    if reference is not None:
                        velocities[topic] = pose_controller.correct(
                            topic, elapsed / schedule.time_scale, reference, velocity)
            self.publish_velocities(velocities)
            if elapsed >= schedule.duration:
                self.finished = True

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    # 保持 ROS context 存活到零速度发送结束，随后再释放节点。
    previous_sigterm = signal.signal(signal.SIGTERM, interrupt)
    node = None
    initialized = False
    try:
        rclpy.init(args=ros_args, signal_handler_options=SignalHandlerOptions.NO)
        initialized = True
        node = PlanPublisher()
        try:
            while rclpy.ok() and not node.finished:
                rclpy.spin_once(node, timeout_sec=0.1)
        except KeyboardInterrupt:
            pass
        finally:
            node.timer.cancel()
            # 结束和 Ctrl+C 均持续发零一小段时间，让传输层有机会投递。
            deadline = time.monotonic() + 0.3
            while rclpy.ok() and time.monotonic() < deadline:
                node.stop_all()
                rclpy.spin_once(node, timeout_sec=0.05)
    finally:
        if node is not None:
            node.destroy_node()
        if initialized and rclpy.ok():
            rclpy.shutdown()
        signal.signal(signal.SIGTERM, previous_sigterm)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, help="指定完整运动或静态计划 JSON")
    parser.add_argument("--time-scale", type=finite_number,
                        help="时间倍率。完整运动默认使用场景速度上限推算的倍率")
    parser.add_argument("--rate", type=finite_number, default=20.0,
                        help="速度发布频率 Hz，默认 20")
    parser.add_argument("--start-delay", type=finite_number, default=1.0,
                        help="发布器建立后等待的秒数，默认 1")
    parser.add_argument("--dry-run", action="store_true",
                        help="输出速度切换时间线，无需 ROS 2")
    args, ros_args = parser.parse_known_args(argv)
    if ros_args and ros_args[0] != "--ros-args":
        parser.error("未知参数 %s" % " ".join(ros_args))
    if (args.rate <= 0 or args.start_delay < 0
            or (args.time_scale is not None and args.time_scale <= 0)):
        parser.error("rate 和 time-scale 必须大于零，start-delay 必须大于或等于零")
    directory = Path(__file__).resolve().parent
    source = args.plan or directory / "motion_commands.json"
    if args.plan is None and not source.is_file():
        source = directory / "plan.json"
    try:
        with source.open(encoding="utf-8") as stream:
            plan = json.load(stream)
        recommended = plan.get("summary", {}).get("recommended_time_scale", 1.0)
        time_scale = args.time_scale if args.time_scale is not None else recommended
        schedule = PlanSchedule(plan, time_scale)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error("无法读取计划 %s — %s" % (source, exc))
    if args.dry_run:
        dry_run(schedule)
        return 0
    try:
        run_ros(schedule, args.rate, args.start_delay, ros_args)
    except ModuleNotFoundError as exc:
        parser.exit(2, "缺少 ROS 2 Python 依赖 %s，请加载 ROS 2 环境；"
                    "可先使用 --dry-run 检查排程。\n" % exc.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
