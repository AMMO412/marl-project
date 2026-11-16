"""Verify the exported ROS 2 publisher without requiring a ROS installation."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from interop.model import Metrics, Plan, Scenario, VelocityCommand
from interop.output import write_outputs
from interop.ros2_plan_node import PlanSchedule, ZERO, run_ros


def sample_plan():
    commands = [
        VelocityCommand(1, "/container_00/robot_001/cmd_vel", 0.3, 0.1),
        VelocityCommand(2, "/container_00/robot_002/cmd_vel", 0.1, 0.1,
                        at_s=0.05, linear_y=0.2, linear_z=0.3,
                        angular_x=0.4, angular_y=0.5, angular_z=0.6),
        VelocityCommand(1, "/container_00/robot_001/cmd_vel", 0.4, 0.1,
                        at_s=0.2),
    ]
    return Plan("ROS-TEST", 1, "test", [], commands, [], [], Metrics(), [])


class Ros2PlanNodeTests(unittest.TestCase):
    def test_generated_topics_include_cmd_vel_and_exported_node_runs(self):
        import fleet
        from interop.message import parse_message
        from interop.scheduler import Planner
        from tests.test_interop import formation, message

        with patch.object(fleet, "CONTAINER_NAME", "container_07"):
            scenario = parse_message(message(), formation())
            plan = Planner(scenario).plan()
            self.assertGreater(len({command.robot_id for command in plan.commands}), 1)
            for command in plan.commands:
                self.assertEqual(
                    command.topic,
                    "/container_07/robot_%03d/cmd_vel" % command.robot_id)
            with tempfile.TemporaryDirectory() as temp:
                paths = write_outputs(plan, scenario, temp)
                data = json.loads(Path(paths["plan_json"]).read_text(
                    encoding="utf-8"))
                schedule = PlanSchedule(data)
                self.assertEqual(set(schedule.rows),
                                 {command.topic for command in plan.commands})
                csv_text = Path(paths["commands_csv"]).read_text(
                    encoding="utf-8-sig")
                cli_text = Path(paths["ros2_commands"]).read_text(
                    encoding="utf-8")
                for topic in schedule.rows:
                    self.assertIn(topic, csv_text)
                    self.assertIn(topic, cli_text)
                result = subprocess.run(
                    [sys.executable, paths["ros2_plan_node"], "--dry-run"],
                    capture_output=True, text=True, check=True)
                summary = json.loads(result.stdout.splitlines()[0])
                self.assertEqual(set(summary["topics"]), set(schedule.rows))

    def test_standalone_topic_fallback_uses_full_cmd_vel_format(self):
        from interop.model import robot_topic
        config = dict(FLEET_CONTAINER_NAME="container_12",
                      FLEET_CMD_SUFFIX="/cmd_vel",
                      FLEET_CMD_TOPIC_TEMPLATE="")
        with patch.dict(sys.modules, {"fleet": None}), patch.dict(
                os.environ, config):
            self.assertEqual(robot_topic(41),
                             "/container_12/robot_041/cmd_vel")

    def test_schedule_handles_gaps_components_and_explicit_stop(self):
        schedule = PlanSchedule(sample_plan().to_dict())
        first, second = schedule.rows
        self.assertEqual(schedule.velocities_at(-1)[first], ZERO)
        self.assertEqual(
            schedule.velocities_at(0.05)[second],
            (0.1, 0.2, 0.3, 0.4, 0.5, 0.6))
        self.assertEqual(schedule.velocities_at(0.1)[first], ZERO)
        self.assertEqual(schedule.velocities_at(0.2)[first][0], 0.4)
        self.assertTrue(all(value == ZERO for value in
                            schedule.velocities_at(schedule.duration).values()))

        plan = sample_plan().to_dict()
        first_command = plan["commands"][0]
        first_command["duration_s"] = 10
        plan["commands"].append(dict(
            first_command, at_s=0.2, duration_s=0, twist={}))
        stopped = PlanSchedule(plan)
        self.assertEqual(stopped.velocities_at(0.2)[first_command["topic"]],
                         ZERO)

    def test_invalid_numeric_plan_is_rejected_before_publishing(self):
        for field, value in (("at_s", -1), ("duration_s", float("nan")),
                             ("duration_s", float("inf"))):
            plan = sample_plan().to_dict()
            plan["commands"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(
                    ValueError):
                PlanSchedule(plan)

    def test_exported_script_runs_from_another_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "output"
            paths = write_outputs(
                sample_plan(), Scenario("test", [], []), str(out))
            manifest = json.loads(Path(paths["manifest_json"]).read_text(
                encoding="utf-8"))
            self.assertIn("ros2_plan_node", manifest["outputs"])
            result = subprocess.run(
                [sys.executable, paths["ros2_plan_node"], "--dry-run"],
                cwd=temp, capture_output=True, text=True, check=True)
            rows = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(rows[0]["commands"], 3)
            self.assertTrue(all(value == list(ZERO)
                                for value in rows[-1]["velocities"].values()))
            spec = importlib.util.spec_from_file_location(
                "exported_node", paths["ros2_plan_node"])
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertAlmostEqual(
                module.PlanSchedule(sample_plan().to_dict()).duration, 0.3)

    def test_ros_timer_path_publishes_and_stops_before_shutdown(self):
        messages = []
        clock = [0]
        lifecycle = []

        class Twist:
            def __init__(self):
                self.linear = SimpleNamespace(x=0., y=0., z=0.)
                self.angular = SimpleNamespace(x=0., y=0., z=0.)

        class Node:
            def __init__(self, name):
                self.callback = None

            def create_publisher(self, message_type, topic, depth):
                def publish(message):
                    values = tuple(
                        getattr(getattr(message, group), axis)
                        for group in ("linear", "angular") for axis in "xyz")
                    messages.append((topic, values))
                return SimpleNamespace(publish=publish)

            def create_timer(self, period, callback):
                self.callback = callback
                return SimpleNamespace(
                    cancel=lambda: setattr(self, "callback", None))

            def get_clock(self):
                return SimpleNamespace(
                    now=lambda: SimpleNamespace(nanoseconds=clock[0]))

            def get_parameter(self, name):
                return SimpleNamespace(value=False)

            def get_logger(self):
                return SimpleNamespace(info=lambda message: None)

            def destroy_node(self):
                lifecycle.append("destroy")

        def spin_once(node, timeout_sec):
            clock[0] += 50_000_000
            if node.callback:
                node.callback()

        modules = {
            name: ModuleType(name) for name in (
                "rclpy", "rclpy.node", "rclpy.signals",
                "geometry_msgs", "geometry_msgs.msg")
        }
        modules["rclpy.node"].Node = Node
        modules["rclpy.signals"].SignalHandlerOptions = SimpleNamespace(NO=0)
        modules["geometry_msgs.msg"].Twist = Twist
        modules["rclpy"].init = lambda **kwargs: lifecycle.append("init")
        modules["rclpy"].ok = lambda: True
        modules["rclpy"].spin_once = spin_once
        modules["rclpy"].shutdown = lambda: lifecycle.append("shutdown")
        with patch.dict(sys.modules, modules):
            run_ros(PlanSchedule(sample_plan().to_dict()), 20, 0, [])
        self.assertIn(
            ("/container_00/robot_002/cmd_vel",
             (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)),
            messages)
        self.assertTrue(all(values == ZERO for _, values in messages[-2:]))
        self.assertEqual(lifecycle, ["init", "destroy", "shutdown"])


if __name__ == "__main__":
    unittest.main()
