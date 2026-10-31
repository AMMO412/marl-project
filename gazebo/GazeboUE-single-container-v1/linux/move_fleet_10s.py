"""Move all 50 robots gently for a bounded capture, then stop every robot."""
import argparse
import time

import rclpy
from geometry_msgs.msg import Twist

parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=float, default=10.0)
args = parser.parse_args()

rclpy.init()
node = rclpy.create_node('move_fleet_for_capture')
publishers = [
    node.create_publisher(Twist, f'/robot_{index:03d}/cmd_vel', 10)
    for index in range(1, 51)
]

try:
    ready_deadline = time.monotonic() + 5.0
    while time.monotonic() < ready_deadline:
        if all(publisher.get_subscription_count() > 0 for publisher in publishers):
            break
        rclpy.spin_once(node, timeout_sec=0.05)

    # Give the capture connection time to receive the initial stationary sample.
    time.sleep(0.5)
    end = time.monotonic() + max(0.0, args.seconds)
    while time.monotonic() < end:
        for index, publisher in enumerate(publishers, start=1):
            command = Twist()
            command.linear.x = 0.18 + (index % 3) * 0.01
            if index <= 30:
                command.angular.z = 0.025 if index % 2 else -0.025
            publisher.publish(command)
        time.sleep(0.05)
finally:
    for _ in range(10):
        for publisher in publishers:
            publisher.publish(Twist())
        time.sleep(0.05)
    node.destroy_node()
    rclpy.shutdown()
