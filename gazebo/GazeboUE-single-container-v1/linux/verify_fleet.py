"""Drive each vehicle separately and measure all 10 ground-truth poses."""
import json, math, time
from pathlib import Path
import rclpy
from rclpy.qos import qos_profile_sensor_data
from geometry_msgs.msg import Twist
from tf2_msgs.msg import TFMessage
rclpy.init()
node=rclpy.create_node('verify_fleet_control')
names=[f'robot_{i:03d}' for i in range(1,51)]
poses={}
def receive(msg):
    for tf in msg.transforms:
        if tf.child_frame_id in names:
            p=tf.transform.translation
            poses[tf.child_frame_id]=[p.x,p.y,p.z]
subs=[node.create_subscription(TFMessage,f'/model/{n}/pose',receive,qos_profile_sensor_data) for n in names]
pubs={n:node.create_publisher(Twist,f'/{n}/cmd_vel',10) for n in names}
def spin(seconds, active=None):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if active:
            msg=Twist(); msg.linear.x=.2
            pubs[active].publish(msg)
        rclpy.spin_once(node,timeout_sec=.02)
def stop_all():
    for _ in range(5):
        for pub in pubs.values(): pub.publish(Twist())
        spin(.05)
report=[]
try:
    spin(3)
    assert len(poses)==50, list(poses)
    for name in names:
        before=dict(poses)
        spin(2, name)
        stop_all(); spin(.3)
        deltas={n:math.dist(before[n],poses[n]) for n in names}
        passed=deltas[name]>.1 and max(d for n,d in deltas.items() if n!=name)<.01
        result=dict(robot=name,displacements_m=deltas,passed=passed)
        report.append(result)
        print(json.dumps(result),flush=True)
    Path(__file__).resolve().parent.parent.joinpath('fleet-control-verification.json').write_text(json.dumps(report,indent=2))
    assert all(r['passed'] for r in report)
finally:
    stop_all(); node.destroy_node(); rclpy.shutdown()
