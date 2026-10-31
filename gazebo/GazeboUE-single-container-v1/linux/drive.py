import time
import argparse
import rclpy
from geometry_msgs.msg import Twist
parser = argparse.ArgumentParser()
parser.add_argument('--robot', type=int, choices=range(1,51), default=1)
parser.add_argument('--linear', type=float, default=0.2)
parser.add_argument('--angular', type=float, default=0.0)
parser.add_argument('--vertical', type=float, default=0.0)
parser.add_argument('--seconds', type=float, default=5.0)
args=parser.parse_args()
if args.robot<=30 and args.vertical!=0:parser.error('Vertical commands are only available for aircraft 31-50.')
rclpy.init()
node = rclpy.create_node(f'ue_robot_{args.robot:03d}_drive')
pub = node.create_publisher(Twist, f'/robot_{args.robot:03d}/cmd_vel', 10)
try:
    deadline=time.monotonic()+10
    while pub.get_subscription_count()==0 and time.monotonic()<deadline:
        rclpy.spin_once(node,timeout_sec=.1)
    if pub.get_subscription_count()==0:raise RuntimeError('No ROS bridge subscriber; start Gazebo first.')
    time.sleep(.3)
    end = time.monotonic() + max(0,args.seconds)
    while time.monotonic() < end:
        msg = Twist()
        msg.linear.x = args.linear
        msg.angular.z = args.angular
        msg.linear.z = args.vertical
        pub.publish(msg)
        time.sleep(0.05)
finally:
    for _ in range(10):
        pub.publish(Twist())
        time.sleep(0.05)
    node.destroy_node()
    rclpy.shutdown()
