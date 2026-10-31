"""Local Gazebo Jetty viewer for the downloaded package; no ROS dependency."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent / 'GazeboUE-single-container-v1'
GENERATED = HERE / 'generated'
RUNTIME = HERE / 'runtime'
os.environ['GZ_PARTITION'] = 'ammo_gazeboue_local_preview'
os.environ['GZ_SIM_RESOURCE_PATH'] = str(PACKAGE / 'assets/environment/models')


def build(view='fleet'):
    GENERATED.mkdir(exist_ok=True)
    RUNTIME.mkdir(exist_ok=True)
    tree = ET.parse(PACKAGE / 'linux/rover_ue.sdf')
    world = tree.getroot().find('world')
    world.set('name', 'local_preview')
    spec = importlib.util.spec_from_file_location('combined_environment', PACKAGE / 'linux/combined_environment.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.apply_combined_environment(world)
    # The portable seed uses legacy rover_XX names; the deployment generator
    # uses robot_XXX. Normalize names and every embedded topic together.
    for model in world.findall('model'):
        match = re.fullmatch(r'rover_(\d{2})', model.get('name', ''))
        if match:
            model.set('name', f'robot_{int(match[1]):03d}')
    for element in world.iter():
        if element.text:
            element.text = re.sub(r'rover_(\d{2})(?!\d)', lambda m: f'robot_{int(m[1]):03d}', element.text)
    for parent in world.iter():
        for plugin in list(parent.findall('plugin')):
            if plugin.get('name') == 'StampedPosePublisher':
                parent.remove(plugin)
                plugin = ET.SubElement(parent, 'plugin', filename='gz-sim-pose-publisher-system', name='gz::sim::systems::PosePublisher')
                ET.SubElement(plugin, 'publish_model_pose').text = 'true'
                ET.SubElement(plugin, 'publish_link_pose').text = 'false'
                ET.SubElement(plugin, 'use_pose_vector_msg').text = 'true'
                ET.SubElement(plugin, 'update_frequency').text = '20'
            else:
                plugin.set('filename', plugin.get('filename', '').replace('ignition-gazebo-', 'gz-sim-'))
                plugin.set('name', plugin.get('name', '').replace('ignition::gazebo::', 'gz::sim::'))
    for uri in world.iter('uri'):
        if uri.text and '/assets/converted/' in uri.text:
            uri.text = str(PACKAGE / 'assets/converted' / Path(uri.text).name)
    # Use a mesh visual: Ogre1 does not position this heightmap visual correctly
    # here, while Ogre2's heightmap shader fails. Physics retains the heightmap.
    mountain = world.find("model[@name='env_yosemite']/link")
    visual = ET.SubElement(mountain, 'visual', name='preview_terrain')
    geometry = ET.SubElement(visual, 'geometry')
    mesh = ET.SubElement(geometry, 'mesh')
    ET.SubElement(mesh, 'uri').text = str(GENERATED / 'yosemite_visual.obj')
    material = ET.SubElement(visual, 'material')
    ET.SubElement(material, 'ambient').text = '0.45 0.43 0.33 1'
    ET.SubElement(material, 'diffuse').text = '0.45 0.43 0.33 1'
    physics = world.find('physics')
    if physics is None:
        physics = ET.SubElement(world, 'physics', name='preview_physics', type='ignored')
    for key, value in [('max_step_size', '0.005'), ('real_time_factor', '1')]:
        element = physics.find(key)
        if element is None:
            element = ET.SubElement(physics, key)
        element.text = value
    ET.indent(tree)
    path = GENERATED / 'preview.sdf'
    tree.write(path, encoding='utf-8', xml_declaration=True)
    config = Path.home().joinpath('.gz/sim/10/gui.config').read_text()
    pose = '-18 -36 14 0 0.55 0.6' if view == 'fleet' else '-310 -330 400 0 0.85 0.8'
    config = re.sub(r'<camera_pose>.*?</camera_pose>', f'<camera_pose>{pose}</camera_pose>', config)
    config = config.replace('show_again="true"', 'show_again="false"')
    # WSL's current Ogre2 backend fails to compile the heightmap shader here.
    # Ogre1 is installed already and supports this terrain preview.
    config = config.replace('<engine>ogre2</engine>', '<engine>ogre</engine>')
    (GENERATED / 'gui.config').write_text(config)
    return path


def drive(robot, linear, angular, seconds):
    import fcntl
    from gz.transport import Node
    from gz.msgs.twist_pb2 import Twist
    from gz.msgs.pose_v_pb2 import Pose_V
    node = Node()
    records = []
    lock = threading.Lock()
    name = f'robot_{robot:03d}'
    RUNTIME.mkdir(exist_ok=True)
    stopfile = RUNTIME / f'{name}.stop'
    driving = seconds > 0 and (linear != 0 or angular != 0)
    # A stop request cancels the ongoing publisher before sending zeros.
    if not driving:
        stopfile.write_text(str(time.time_ns()))
    lockfile = None
    initial_stop = stopfile.read_text() if stopfile.exists() else ''
    if driving:
        lockfile = (RUNTIME / f'{name}.drive.lock').open('w')
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('This robot is already moving. Stop it before starting another movement.')
    def receive(msg):
        for pose in msg.pose:
            if pose.name == name:
                with lock:
                    stamp = pose.header.stamp if pose.header.HasField('stamp') else msg.header.stamp
                    records.append(dict(wall=time.time(), sim_time=stamp.sec + stamp.nsec / 1e9,
                                        x=pose.position.x, y=pose.position.y, z=pose.position.z))
    if not node.subscribe(Pose_V, f'/model/{name}/pose', receive):
        raise RuntimeError('Pose subscription failed')
    pub = node.advertise(f'/{name}/cmd_vel', Twist)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        with lock:
            ready = bool(records)
        if (ready or not driving) and pub.has_connections():
            break
        time.sleep(.1)
    else:
        raise RuntimeError('No running preview or pose feedback. Open the preview first.')
    try:
        print(f'{name}: sending command; stop script can interrupt this movement.', flush=True)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if driving and (stopfile.read_text() if stopfile.exists() else '') != initial_stop:
                print('Movement cancelled by stop request.', flush=True)
                break
            msg = Twist()
            msg.linear.x, msg.angular.z = linear, angular
            pub.publish(msg)
            time.sleep(.05)
    finally:
        for _ in range(12):
            pub.publish(Twist())
            time.sleep(.05)
    time.sleep(1)
    if lockfile:
        lockfile.close()
    with lock:
        saved = list(records)
    if not saved and not driving:
        print('Stop request sent. No pose sample received, so standstill was not verified.', flush=True)
        return
    displacement = math.hypot(saved[-1]['x'] - saved[0]['x'], saved[-1]['y'] - saved[0]['y'])
    settled = [p for p in saved if p['wall'] >= saved[-1]['wall'] - .5]
    stop_drift = math.hypot(settled[-1]['x'] - settled[0]['x'], settled[-1]['y'] - settled[0]['y'])
    report = dict(robot=name, command=dict(linear=linear, angular=angular, wall_seconds=seconds),
                  displacement_m=displacement, feedback_samples=len(saved), first=saved[0], last=saved[-1],
                  stop_drift_last_half_wall_second_m=stop_drift,
                  note='Gazebo Jetty direct transport preview; not ROS/container integration')
    RUNTIME.mkdir(exist_ok=True)
    target = RUNTIME / f'drive_{time.time_ns()}.json'
    target.write_text(json.dumps(dict(report=report, poses=saved), indent=2))
    print(json.dumps(report, indent=2), flush=True)
    print('Record:', target, flush=True)
    if seconds > 0 and linear != 0 and displacement < .05:
        raise RuntimeError('Command sent but motion was not verified; check pause state and logs')
    if stop_drift > .03:
        raise RuntimeError('Robot has not settled after stop; check feedback record')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['open', 'build', 'drive', 'stop', 'close', 'screenshot', 'view'])
    parser.add_argument('--view', choices=['fleet', 'overview'], default='fleet')
    parser.add_argument('--robot', type=int, choices=range(1, 51), default=1)
    parser.add_argument('--linear', type=float, default=.5)
    parser.add_argument('--angular', type=float, default=0.)
    parser.add_argument('--seconds', type=float, default=10.)
    args = parser.parse_args()
    if args.action == 'view':
        if args.view == 'fleet':
            x, y, z, pitch, yaw = -18, -36, 14, .55, .6
        else:
            x, y, z, pitch, yaw = -310, -330, 400, .85, .8
        qx = -math.sin(pitch / 2) * math.sin(yaw / 2)
        qy = math.sin(pitch / 2) * math.cos(yaw / 2)
        qz = math.cos(pitch / 2) * math.sin(yaw / 2)
        qw = math.cos(pitch / 2) * math.cos(yaw / 2)
        request = 'pose { position { x: %s y: %s z: %s } orientation { x: %s y: %s z: %s w: %s } }' % (x, y, z, qx, qy, qz, qw)
        result = subprocess.run(['gz', 'service', '-s', '/gui/move_to/pose', '--reqtype', 'gz.msgs.GUICamera', '--reptype', 'gz.msgs.Boolean', '--timeout', '10000', '--req', request], check=True, capture_output=True, text=True)
        if 'data: true' not in result.stdout:
            raise RuntimeError('Camera change failed. Open the preview and wait for the scene to load. ' + result.stdout + result.stderr)
        print('Camera changed to ' + args.view, flush=True)
        return
    if args.action == 'screenshot':
        target = RUNTIME / 'screenshots'
        target.mkdir(exist_ok=True)
        before = set(target.glob('*.png'))
        result = subprocess.run(['gz', 'service', '-s', '/gui/screenshot', '--reqtype', 'gz.msgs.StringMsg', '--reptype', 'gz.msgs.Boolean', '--timeout', '15000', '--req', f'data: "{target}"'], check=True, capture_output=True, text=True)
        if 'data: true' not in result.stdout:
            raise RuntimeError('GUI screenshot service failed: ' + result.stdout + result.stderr)
        deadline = time.monotonic() + 60
        files = []
        while time.monotonic() < deadline:
            files = list(set(target.glob('*.png')) - before)
            if files and files[0].stat().st_size > 0:
                time.sleep(.3)
                break
            time.sleep(.2)
        if not files:
            raise RuntimeError('No screenshot was written; check GUI log')
        latest = max(files, key=lambda p: p.stat().st_mtime)
        safe = latest.with_name(latest.name.replace(':', '-'))
        if safe != latest:
            latest.rename(safe)
        print(safe)
        return
    if args.action == 'close':
        for kind in ['gui', 'server']:
            path = RUNTIME / f'{kind}.pid'
            if path.exists():
                pid = int(path.read_text())
                try:
                    cmd = Path(f'/proc/{pid}/cmdline').read_text()
                    if str(GENERATED) in cmd:
                        os.killpg(pid, signal.SIGTERM)
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline:
                            if not Path(f'/proc/{pid}/cmdline').exists() or not Path(f'/proc/{pid}/cmdline').read_bytes():
                                break
                            time.sleep(.1)
                except (FileNotFoundError, ProcessLookupError):
                    pass
                path.unlink(missing_ok=True)
        print('Local preview stopped.')
        return
    if not all(map(math.isfinite, (args.linear, args.angular, args.seconds))) or not 0 <= args.seconds <= 30 or abs(args.linear) > 1 or abs(args.angular) > 1:
        parser.error('Use finite values: seconds 0..30, linear/angular -1..1')
    if args.action in ['drive', 'stop']:
        drive(args.robot, args.linear if args.action == 'drive' else 0, args.angular if args.action == 'drive' else 0, args.seconds if args.action == 'drive' else 0)
        return
    if args.action == 'build':
        print(build(args.view))
        return
    # Isolated transport partition. Reuse our server only, never stop another simulation.
    pidfile = RUNTIME / 'server.pid'
    alive = False
    if pidfile.exists():
        pid = int(pidfile.read_text())
        try:
            alive = 'preview.sdf' in Path(f'/proc/{pid}/cmdline').read_text()
        except FileNotFoundError:
            pass
    if not alive:
        print('Preparing scene and starting Gazebo server...', flush=True)
        path = build(args.view)
        with (RUNTIME / 'server.log').open('a') as log:
            proc = subprocess.Popen(['gz', 'sim', '-s', '-r', '-v', '3', str(path)], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        pidfile.write_text(str(proc.pid))
    guipid = RUNTIME / 'gui.pid'
    if guipid.exists():
        try:
            if str(GENERATED) in Path(f'/proc/{int(guipid.read_text())}/cmdline').read_text():
                print('Preview window exists. Checking that a rendered frame is available...', flush=True)
                subprocess.run([sys.executable, str(HERE / 'preview.py'), 'screenshot'], check=True)
                print('Gazebo is ready. Use its existing window.', flush=True)
                return
        except FileNotFoundError:
            pass
    os.environ['QT_QPA_PLATFORM'] = 'xcb'
    os.environ.pop('WAYLAND_DISPLAY', None)
    with (RUNTIME / 'gui.log').open('a') as log:
        proc = subprocess.Popen(['gz', 'sim', '-g', '-v', '3', '--gui-config', str(GENERATED / 'gui.config')], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (RUNTIME / 'gui.pid').write_text(str(proc.pid))
    print(f'Loading models, please wait (up to 90 seconds). GUI PID {proc.pid}.', flush=True)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'Gazebo window exited. Check {RUNTIME / "gui.log"}')
        result = subprocess.run(['gz', 'service', '-l'], capture_output=True, text=True, timeout=8)
        if '/gui/move_to/pose' in result.stdout and '/world/local_preview/scene/info' in result.stdout:
            # Service creation precedes mesh loading. Screenshot waits for a
            # rendered frame and makes initialization failures visible.
            subprocess.run([sys.executable, str(HERE / 'preview.py'), 'screenshot'], check=True)
            print('Gazebo is ready. You can now run the movement or camera scripts.', flush=True)
            return
        time.sleep(2)
    raise RuntimeError(f'Gazebo did not become ready. Logs: {RUNTIME}')


if __name__ == '__main__':
    main()
