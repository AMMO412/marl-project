"""Build ROS velocity playback from motion executed by the local simulator."""

from collections import defaultdict
import csv
import json
import math
import xml.etree.ElementTree as ET

from fleet import pose_topic_of


PLAYBACK_FORMAT = 'workbench-motion-replay/v1'


def sdf_drive_limits(formation_meta):
    source = formation_meta.get('source_sdf_path') or formation_meta.get('source_sdf')
    if not source:
        return {}
    from city_nav import resolve_sdf
    path = resolve_sdf(source)
    if not path.is_file():
        return {}
    limits = {}
    for model in ET.parse(path).getroot().iter('model'):
        name = model.get('name', '')
        if not name.startswith('robot_') or not name[6:].isdigit():
            continue
        for plugin in model.findall('plugin'):
            if 'diff-drive' not in plugin.get('filename', ''):
                continue
            values = {}
            for axis in ('linear', 'angular'):
                for quantity in ('velocity', 'acceleration'):
                    limit = plugin.findtext(f'max_{axis}_{quantity}')
                    if limit is not None and float(limit) > 0:
                        values[f'{axis}_{quantity}'] = float(limit)
            limits[int(name[6:])] = values
    return limits


def _twist(before, after, duration, scale, aircraft):
    """Fit one body-frame twist to the sampled displacement and heading change."""
    x, y, z, yaw = before
    end_x, end_y, end_z, end_yaw = after
    turn = math.atan2(math.sin(end_yaw - yaw), math.cos(end_yaw - yaw))
    heading = yaw + turn / 2
    dx, dy = end_x - x, end_y - y
    # A constant body velocity rotates throughout the interval. Compensate for
    # the difference between the circular arc and its chord.
    arc = (turn / 2) / math.sin(turn / 2) if abs(turn) > 1e-8 else 1.0
    factor = scale * arc / duration
    forward = (math.cos(heading) * dx + math.sin(heading) * dy) * factor
    lateral = (-math.sin(heading) * dx + math.cos(heading) * dy) * factor
    return dict(linear=dict(x=round(forward, 8), y=round(lateral, 8) if aircraft else 0.0,
                            z=round((end_z - z) * scale / duration, 8) if aircraft else 0.0),
                angular=dict(x=0.0, y=0.0, z=round(turn / duration, 8)))


class MotionReplay:
    def __init__(self, platforms, units, scale, drive_limits=None):
        self.platforms = platforms
        self.units = units
        self.scale = scale
        self.drive_limits = drive_limits or {}
        self.samples = defaultdict(list)
        self.participants = {}

    def record(self, pid, at_s, duration, phase, before, after, command):
        platform = self.platforms[pid]
        self.participants.setdefault(pid, dict(
            robot_id=platform.robot_no, worker_id=pid, unit_id=self.units.get(pid),
            topic=platform.topic, pose_topic=pose_topic_of(platform.robot_no),
            aircraft=platform.can_climb, initial_pose=self._metric_pose(before),
        ))
        action = phase
        if phase not in ('return', 'landing'):
            if platform.can_climb and after[2] > before[2] and before[2] == 0:
                action = 'takeoff'
            elif phase in ('travel', '机动') or phase.startswith('机动'):
                action = 'travel'
            elif phase != 'loiter':
                action = 'hold' if before == after else 'work'
        twist = _twist(before, after, duration, self.scale, platform.can_climb)
        self.samples[pid].append(dict(
            at_s=round(at_s, 6), duration_s=round(duration, 6), phase=action,
            behavior_phase=phase,
            task_id=command['job_id'] if command else None,
            source_command_id=command['command_id'] if command else None,
            attempt=command['attempt'] if command else None,
            start_pose=self._metric_pose(before), end_pose=self._metric_pose(after),
            twist=twist,
        ))

    def _metric_pose(self, pose):
        return [round(value * self.scale, 8) for value in pose[:3]] + [round(pose[3], 8)]

    def write(self, out, report, slots):
        commands = []
        discontinuities = []
        platforms = list(self.participants.values())
        for platform in platforms:
            pid = platform['worker_id']
            platform['drive_limits'] = self.drive_limits.get(platform['robot_id'], {})
            home = report.get('returns', {}).get(pid, {}).get('home')
            if home is not None:
                platform['home'] = [round(value * self.scale, 8) for value in home]
            platform['return_status'] = report.get('returns', {}).get(pid, {}).get('status')
            last = None
            for sample in sorted(self.samples[pid], key=lambda row: row['at_s']):
                if last is not None:
                    end_s = round(last['at_s'] + last['duration_s'], 6)
                    if sample['at_s'] < end_s - 1e-6:
                        raise ValueError(f'{pid} 的运动指令存在重叠时段')
                    gap = math.dist(last['end_pose'][:3], sample['start_pose'][:3])
                    if gap > 1e-3:
                        discontinuities.append(dict(worker_id=pid, at_s=sample['at_s'],
                                                    distance_m=round(gap, 4)))
                command_id = sample['source_command_id']
                row = dict(sample, robot_id=platform['robot_id'], unit_id=platform['unit_id'],
                           topic=platform['topic'], subtask_id=slots.get(command_id))
                commands.append(row)
                last = row
            if last and platform['return_status'] == 'returned':
                at_s = round(last['at_s'] + last['duration_s'], 6)
                pose = last['end_pose']
                commands.append(dict(
                    last, at_s=at_s, duration_s=0.1, phase='stop', behavior_phase='returned',
                    task_id=None, source_command_id=None, attempt=None, subtask_id=None,
                    start_pose=pose, twist=_twist(pose, pose, 0.1, 1.0, platform['aircraft'])))
        platforms.sort(key=lambda row: row['robot_id'])
        commands.sort(key=lambda row: (row['robot_id'], row['at_s']))
        for i, row in enumerate(commands, 1):
            row['command_id'] = 'MOTION-%06d' % i
        phases = sorted({row['phase'] for row in commands})
        complete = (report.get('all_succeeded') and report.get('return_complete') and not discontinuities
                    and all(platform['return_status'] == 'returned' for platform in platforms))
        time_scale = self._time_scale(commands)
        time_scale = math.ceil(time_scale * 100) / 100
        summary = dict(status='complete' if complete else 'partial',
                       command_count=len(commands), phases=phases,
                       platform_count=len(platforms), pose_feedback='disabled',
                       discontinuity_count=len(discontinuities), recommended_time_scale=time_scale)
        data = dict(format=PLAYBACK_FORMAT, run_id=report['run_id'],
                    velocity_frame='body', position_units='m', time_units='s',
                    feedback_type='geometry_msgs/msg/PoseStamped',
                    summary=summary, platforms=platforms, discontinuities=discontinuities,
                    commands=commands)
        (out / 'motion_commands.json').write_text(
            json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
        axes = [f'{group}_{axis}' for group in ('linear', 'angular') for axis in 'xyz']
        fields = ['command_id', 'source_command_id', 'attempt', 'robot_id', 'unit_id', 'topic',
                  'task_id', 'subtask_id', 'phase', 'behavior_phase', 'at_s', 'duration_s', *axes]
        with (out / 'motion_commands.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in commands:
                values = {key: row[key] for key in fields if key not in axes}
                values.update({f'{group}_{axis}': value for group, vector in row['twist'].items()
                               for axis, value in vector.items()})
                writer.writerow(values)
        return summary

    def _time_scale(self, commands):
        scale = 1.0
        previous = {}
        for row in commands:
            robot = row['robot_id']
            limits = self.drive_limits.get(robot)
            if not limits:
                continue
            last = previous.get(robot)
            if last and last['at_s'] + last['duration_s'] < row['at_s'] - 1e-6:
                last = None
            for group, axis in (('linear', 'x'), ('angular', 'z')):
                speed = row['twist'][group][axis]
                before = last['twist'][group][axis] if last else 0.0
                accel = abs(speed - before) / row['duration_s']
                scale = max(scale, abs(speed) / limits.get(f'{group}_velocity', math.inf),
                            math.sqrt(accel / limits.get(f'{group}_acceleration', math.inf)))
            previous[robot] = row
        return scale
