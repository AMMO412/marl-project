"""Read-only adapter for the saved, serial behavior verification recording.

Coordinates, phase events and route geometry are copied from the source JSON.
Recording boundaries are explicitly named; no planner/feedback audit is invented.
"""
import hashlib
import json
import math
from pathlib import Path

RECORDING_ID = 'behavior_20261028_verify'


def load_recording(root):
    from trajectory_v2 import KIND_NAME, KIND_SHAPE, kind_of
    root = Path(root)
    source = root / 'outputs' / RECORDING_ID / 'behavior_trace.json'
    raw = source.read_bytes()
    saved = json.loads(raw.decode('utf-8-sig'))
    scenario = json.loads((root / 'scenarios/simple_city.json').read_text(encoding='utf-8-sig'))
    scenario_jobs = {j['job_id']: j for j in scenario['jobs']}
    platforms = {p.get('pid', 'rover_%02d' % p['robot_no']): p
                 for p in scenario['platforms']}
    workers, structures, trace, jobs = {}, [], [], []
    for job in saved['jobs']:
        jid, start, end = job['job_id'], job['t0'], job['t1']
        original = scenario_jobs[jid]
        metrics = job['metrics']
        structure = dict(job_id=jid, type=job['kind'], site=job['site'], sim_s=start)
        for key in ('loop', 'posts', 'staging', 'objective', 'area_radius',
                    'sensor_radius', 'ring_radius', 'outer_radius', 'confirm_radius'):
            if key in metrics:
                structure[key] = metrics[key]
        if job['kind'] == 'hold' and len(job['pids']) > 1:
            standby = next((r['to'] for r in job['routes']
                            if r['pid'] == job['pids'][1]), None)
            structure['standbys'] = [standby] if standby else []
        structures.append(structure)
        trace.append(dict(kind='recording_start', sim_s=start, job_id=jid,
                          pids=job['pids'], attempt=1, planned_start=None,
                          planned_end=None, source='saved_recording_boundary'))
        trace.append(dict(kind='behavior_event', sim_s=start,
                          event=dict(kind='behavior_structure', **structure)))
        for event in job['events']:
            trace.append(dict(kind='behavior_event', sim_s=event['t'],
                              event=event, source='saved_behavior_event'))
        for route in job['routes']:
            # Unlike sample/event t, route t in this saved format is job-local.
            when = start + route['t']
            trace.append(dict(kind='behavior_event', sim_s=when,
                              event=dict(kind='approach_route', job_id=jid,
                                         route=dict(route, recorded_at_sim_s=when)),
                              source='saved_route'))
        last_second = None
        for sample in job['samples']:
            when = sample['t']
            second = math.floor(when + 1e-7)
            if second != last_second:
                last_second = second
                trace.append(dict(kind='behavior_event', sim_s=when,
                                  event=dict(kind='behavior_detail', job_id=jid,
                                             phase=sample['phase'],
                                             debug=sample.get('debug', {}),
                                             params={}, routes=[]),
                                  source='saved_sample'))
            for pid, position in sample['agents'].items():
                if pid not in workers:
                    platform = platforms.get(pid, {})
                    kind = platform.get('kind') or kind_of(int(pid.rsplit('_', 1)[1]))
                    workers[pid] = dict(pid=pid, kind=kind,
                                        no=platform.get('robot_no'),
                                        kind_name=KIND_NAME.get(kind, kind),
                                        shape=KIND_SHAPE.get(kind, 'square'),
                                        start=position[:2], start_z=0,
                                        initial_battery=None, samples=[])
                workers[pid]['samples'].append(dict(t=when, x=position[0],
                    y=position[1], yaw=position[2], z=0, battery=None, job=jid,
                    status='progress', phase=sample['phase'],
                    command='recording:' + jid, progress=None))
        trace.append(dict(kind='recording_end', sim_s=end, job_id=jid,
                          succeeded=job['phase'] == '完成',
                          source='saved_recording_boundary'))
        jobs.append(dict(job_id=jid, jtype=job['kind'], pos=original['pos'],
                         work=1, window=[start, end],
                         crew=len(job['pids']), need_sensor=original.get('need_sensor'),
                         status='succeeded' if job['phase'] == '完成' else 'failed',
                         started_at=start, planned_end=None, attempts=1,
                         progress=1 if job['phase'] == '完成' else 0))
    for worker in workers.values():
        worker['samples'].sort(key=lambda s: s['t'])
        distance = 0
        previous = worker['start']
        for sample in worker['samples']:
            distance += math.hypot(sample['x'] - previous[0], sample['y'] - previous[1])
            sample['distance'] = distance
            previous = [sample['x'], sample['y']]
        worker.update(distance=distance, displacement=math.dist(worker['start'], previous))
    trace.sort(key=lambda e: e['sim_s'])
    provenance = dict(kind='saved_serial_recording', path=str(source),
                      sha256=hashlib.sha256(raw).hexdigest(),
                      label='专项验证记录 · 串行回放',
                      note='读取指定的已保存专项记录；与当前并行运行分开展示。')
    done = sum(j['status'] == 'succeeded' for j in jobs)
    report = dict(run_id=RECORDING_ID, protocol='saved-behavior-recording/v1',
                  recording=True, recording_source=provenance,
                  jobs=jobs, platforms=[], behavior=True, behavior_details=True,
                  motion='real', avoid=True, mode='recording', objective=None,
                  done=done, all_succeeded=done == len(jobs), settled=True,
                  simulated_until_s=saved['total'], plans=None, used_energy=None,
                  retries=None, timeouts=None, triggers={})
    return dict(id=RECORDING_ID, report=report, scenario=scenario,
                trace=trace, replay=dict(workers=list(workers.values()),
                    jobs=scenario['jobs'], behaviors=structures, end=saved['total'],
                    background={}, motion='real', behavior=True),
                obstacles=saved['obstacles'], geometry_note='原记录碰撞体',
                manifest=dict(source=provenance, read_only=True,
                              synthesized_fields=['recording_start', 'recording_end',
                                                  'binary_completion_indicator']),
                files=['behavior_trace.json', 'behavior_demo.html'])
