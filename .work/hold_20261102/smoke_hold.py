# -*- coding: utf-8 -*-
"""KeepBehavior 手工冒烟：用"瞬移到位"把决策与运动解耦。"""
import sys
sys.path.insert(0, 'planning_middle_demo')

from behaviors import KeepBehavior


class _Nav:
    bounds = (-500.0, -500.0, 500.0, 500.0)
    radius = 1.0

    def nearest_free(self, point, max_radius=4.0):
        return [float(point[0]), float(point[1])], 0.0

    def free(self, point, radius=None):
        return True


def params(**over):
    base = dict(
        key_point=[0, 40],
        positions=[dict(id='P1', point=[0, 70], facing_deg=0),
                   dict(id='P2', point=[35, 40], facing_deg=90),
                   dict(id='P3', point=[20, 18], facing_deg=135)],
        stations=dict(reserve=[-21.2, 18.8], support=[], relay=[0, 40]),
        threats=[dict(id='N', bearing_deg=0, width_deg=70),
                 dict(id='E', bearing_deg=90, width_deg=60)],
        roles={'U1': 'post:P1', 'U2': 'post:P2', 'U3': 'post:P3',
               'U4': 'reserve:standby'},
        min_on_post=2, sensor_radius_m=40, duration_s=120, max_steps=400,
        relief=dict(interval_s=60, handover_tol_m=3,
                    swap_requires_arrival=True, relief_cycles=2),
        relief_interval_s=60, relief_cycles=2,
        reinforce=dict(trigger='position_lost', enemy_ratio=1.5,
                       arrive_within_s=60),
        reinforce_ratio=1.5, reinforce_arrive_within_s=60,
        withdraw=dict(allowed=True, route=[[0, 40], [-60, -20]],
                      deadline_s=60),
        enemy_events=[dict(t_s=20, kind='probe', direction='N'),
                      dict(t_s=40, kind='assault', direction='N', ratio=1.6),
                      dict(t_s=80, kind='probe', direction='E')],
        counter_attack=dict(authorized=True, max_range_m=80),
        effect=dict(kinds=['damage', 'suppress'], required_duration=5),
    )
    base.update(over)
    return base


job = dict(job_id='T1', type='hold', pos=[0, 40])
nav = _Nav()
behavior = KeepBehavior(job, nav, ['U1', 'U2', 'U3', 'U4'], params())
poses = {pid: (float(p[0]), float(p[1]), 0.0) for pid, p in
         ((pid, behavior._station_of(pid)) for pid in behavior.pids)}
for t in range(500):
    out = behavior.step(poses, float(t), 1.0)
    for pid, target in out['targets'].items():
        poses[pid] = (float(target[0]), float(target[1]), 0.0)
    if out['done']:
        break

seen = []
for ev in behavior.history:
    if ev['kind'] in ('phase', 'arrived_area'):
        continue
    if ev['kind'] in seen:
        continue
    seen.append(ev['kind'])
print('events:', seen)
print('verdict:', behavior.verdict['verdict'], '|', behavior.verdict['reason'])
for item in behavior.verdict['items']:
    print('  item', item['id'], item['ok'], item['required'], item['value'],
          '/', item['target'])
print('handovers:', behavior.handover_list)
print('reinforce:', behavior.reinforce_list)
print('effects:', [(e['overall'], e['verified']) for e in behavior.effects])
print('metrics:', {k: v for k, v in behavior.metrics.items()
                   if k in ('control_hold_ratio', 'control_interruption_s',
                            'observation_gap_max_s', 'enemy_attacks',
                            'enemy_breaches', 'relief_count', 'our_losses',
                            'control_established_at_s', 'hold_span_s')})
