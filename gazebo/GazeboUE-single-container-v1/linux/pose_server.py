"""ROS ground-truth model pose -> TCP NDJSON. Windows connects to localhost:8765.

Latest-state display prototype; not lockstep simulation or a real-time guarantee.
"""
import json
import socket
import subprocess
import threading
import time
import uuid
import os
from pathlib import Path
import rclpy
from rclpy.qos import qos_profile_sensor_data
from tf2_msgs.msg import TFMessage

INSTANCE_ID=os.environ.get('GAZEBO_INSTANCE_ID','container_00')
ROBOT_TYPES={f'robot_{i:03d}':('ugv' if i<=20 else 'tank' if i<=30 else 'plane' if i<=40 else 'flying_wing') for i in range(1,51)}
LISTEN_HOST=os.environ.get('POSE_SERVER_HOST','127.0.0.1')
POSE_PORT=int(os.environ.get('POSE_SERVER_PORT','8765'))
CLOCK_PORT=int(os.environ.get('CLOCK_SERVER_PORT','8766'))
RESCAN_INTERVAL=float(os.environ.get('BRIDGE_RESCAN_INTERVAL','5'))
STALE_AFTER=float(os.environ.get('BRIDGE_STALE_AFTER','5'))
RETRY_AFTER=float(os.environ.get('BRIDGE_RETRY_AFTER','10'))
INITIAL_GRACE=float(os.environ.get('BRIDGE_INITIAL_GRACE','15'))

class LatestPose:
    def __init__(self):
        self.lock = threading.Lock()
        self.packets = {}
        self.sequence = 0
        self.last_stamps = {}
        self.last_received = {}
        self.transforms = {}
        self.epoch = 0
        self.session = uuid.uuid4().hex
        runtime_dir = Path(os.environ.get('GAZEBO_UE_RUNTIME_DIR', Path(__file__).parent))
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.trace = (runtime_dir/'source_trace.csv').open('w',buffering=65536)
        self.trace.write('robot,source_seq,sim_ns,source_unix,bridge_unix,source_raw,bridge_raw\n')
        self.trace_start=time.monotonic()

    def receive(self, message):
        for tf in message.transforms:
            if tf.child_frame_id not in ROBOT_TYPES:
                continue
            # PosePublisher model pose is relative to the parent world.
            frame_parts=tf.header.frame_id.split('|')
            if frame_parts[0] not in (INSTANCE_ID, 'world', f'world/{INSTANCE_ID}'):
                continue
            stamp = tf.header.stamp.sec * 1000000000 + tf.header.stamp.nanosec
            p, q = tf.transform.translation, tf.transform.rotation
            with self.lock:
                name = tf.child_frame_id
                if name in self.last_stamps and stamp < self.last_stamps[name]:
                    self.epoch += 1
                self.sequence += 1
                self.last_stamps[name] = stamp
                self.last_received[name] = time.monotonic()
                self.transforms[name] = tf
                packet = dict(version=1, session=self.session, epoch=self.epoch, seq=self.sequence,
                              sim_sec=tf.header.stamp.sec, sim_nanosec=tf.header.stamp.nanosec,
                              instance_id=INSTANCE_ID, robot_name=name,
                              robot_id=f'{INSTANCE_ID}/{name}', robot_type=ROBOT_TYPES[name], frame=frame_parts[0],
                              position=[p.x,p.y,p.z], quaternion=[q.x,q.y,q.z,q.w])
                if len(frame_parts)==4:
                    packet['source_unix']=int(frame_parts[1])/1e9
                    packet['source_seq']=int(frame_parts[2])
                    packet['bridge_unix']=time.time()
                    packet['source_raw']=int(frame_parts[3])/1e9
                    packet['bridge_raw']=time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)/1e9
                    if time.monotonic()-self.trace_start<300:
                        self.trace.write(f"{name},{packet['source_seq']},{stamp},{packet['source_unix']:.9f},{packet['bridge_unix']:.9f},{packet['source_raw']:.9f},{packet['bridge_raw']:.9f}\n")
                self.packets[name] = (self.sequence, (json.dumps(packet, allow_nan=False) + '\n').encode())

    def aggregate_message(self):
        """Return the latest 50 poses on the legacy-compatible aggregate topic."""
        with self.lock:
            if len(self.transforms) != len(ROBOT_TYPES):
                return None
            return TFMessage(
                transforms=[self.transforms[name] for name in sorted(ROBOT_TYPES)]
            )

    def active_robots(self, stale_after):
        now = time.monotonic()
        with self.lock:
            return {name for name, received in self.last_received.items()
                    if now - received <= stale_after}

    def client_loop(self, client, stop):
        with client:
            client.settimeout(1)
            sent = {}
            while not stop.is_set():
                with self.lock:
                    current = dict(self.packets)
                for name, (seq, packet) in current.items():
                    if sent.get(name) == seq:
                        continue
                    try:
                        client.sendall(packet)
                    except OSError:
                        return
                    sent[name] = seq
                stop.wait(0.01)

    def serve(self, stop):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((LISTEN_HOST,POSE_PORT))
            listener.listen(64)
            listener.settimeout(0.5)
            print(f'POSE_SERVER_READY {LISTEN_HOST}:{POSE_PORT}', flush=True)
            while not stop.is_set():
                try:
                    client, _ = listener.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self.client_loop, args=(client,stop), daemon=True).start()

class BridgeRepairManager:
    """Start supplemental bridge waves for pose streams missed during discovery."""
    def __init__(self, node, latest, runtime_dir):
        self.node = node
        self.latest = latest
        self.processes = []
        self.created_at = time.monotonic()
        self.last_start = 0.0
        self.log = (runtime_dir/'bridge_repair.log').open('a', buffering=1)
        self.timer = node.create_timer(RESCAN_INTERVAL, self.scan)

    def _start(self, missing):
        mappings = [f'/model/{name}/pose@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V'
                    for name in missing]
        process = subprocess.Popen(
            ['ros2', 'run', 'ros_gz_bridge', 'parameter_bridge', *mappings],
            stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append(process)
        self.last_start = time.monotonic()
        print(f'BRIDGE_REPAIR_START count={len(missing)} pid={process.pid} '
              f'robots={",".join(missing)}', flush=True)

    def scan(self):
        now = time.monotonic()
        active = self.latest.active_robots(STALE_AFTER)
        missing = sorted(set(ROBOT_TYPES) - active)
        self.processes = [process for process in self.processes
                          if process.poll() is None]
        ready = now - self.created_at >= INITIAL_GRACE
        if missing and ready and now - self.last_start >= RETRY_AFTER:
            self._start(missing)
        print(f'BRIDGE_RESCAN active={len(active)} missing={len(missing)}', flush=True)

    def close(self):
        self.timer.cancel()
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
        for process in self.processes:
            if process.poll() is None:
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        self.log.close()

def clock_service(stop):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind((LISTEN_HOST,CLOCK_PORT));listener.listen(2);listener.settimeout(.5)
        while not stop.is_set():
            try:client,_=listener.accept()
            except socket.timeout:continue
            with client:
                client.settimeout(2);client.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                while not stop.is_set():
                    try:
                        data=client.recv(32);t2=time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
                        if not data:break
                        client.sendall(f'{t2},{time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)}\n'.encode())
                    except OSError:break

if __name__ == '__main__':
    rclpy.init()
    node = rclpy.create_node(f'gazebo_ue_pose_server_{INSTANCE_ID}')
    latest = LatestPose()
    subs = [node.create_subscription(TFMessage, f'/model/robot_{i:03d}/pose', latest.receive, qos_profile_sensor_data) for i in range(1,51)]
    aggregate_pub = node.create_publisher(
        TFMessage, '/gazebo/model_states', qos_profile_sensor_data
    )
    aggregate_timer = node.create_timer(
        0.05,
        lambda: (
            aggregate_pub.publish(message)
            if (message := latest.aggregate_message()) is not None
            else None
        ),
    )
    runtime_dir = Path(os.environ.get('GAZEBO_UE_RUNTIME_DIR', Path(__file__).parent))
    repair = BridgeRepairManager(node, latest, runtime_dir)
    stop = threading.Event()
    worker = threading.Thread(target=latest.serve, args=(stop,), daemon=True)
    worker.start()
    threading.Thread(target=clock_service,args=(stop,),daemon=True).start()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        repair.close()
        worker.join(timeout=2)
        latest.trace.close()
        node.destroy_node()
        rclpy.try_shutdown()
