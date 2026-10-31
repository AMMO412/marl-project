"""Verify the aggregate /gazebo/model_states topic inside one container."""

import argparse
import json
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from tf2_msgs.msg import TFMessage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    expected = {f"robot_{number:03d}" for number in range(1, 51)}
    result = {"received": 0, "missing": sorted(expected), "passed": False}
    rclpy.init()
    node = rclpy.create_node("verify_gazebo_model_states")

    def receive(message):
        names = {transform.child_frame_id for transform in message.transforms}
        missing = expected - names
        result.update(
            received=len(expected & names),
            missing=sorted(missing),
            passed=not missing,
        )

    subscription = node.create_subscription(
        TFMessage, "/gazebo/model_states", receive, qos_profile_sensor_data
    )
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline and not result["passed"]:
        rclpy.spin_once(node, timeout_sec=0.2)
    print(json.dumps(result))
    node.destroy_subscription(subscription)
    node.destroy_node()
    rclpy.shutdown()
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
