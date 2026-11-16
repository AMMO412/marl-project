"""Tick-boundary controls for an interactive local simulation."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from uuid import uuid4
import time

from contracts_v2 import build_jobs, check_scenario_v2
from fleet import pid_of
from interop.gate import target_inside_no_go
from interop.message import parse_message, target_points
from interop.runtime import to_v2_dict
from interop.scheduler import Planner
from interop.templates import decompose
from workbench_task_editor import editor_task_types, is_editable_task


def write_json(path, data):
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    try:
        # Windows readers can briefly hold a handle that denies replacement.
        for attempt in range(40):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.025)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path):
    # A reader can catch a writer between truncation and flush on Windows.
    for _ in range(8):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, PermissionError):
            time.sleep(0.015)
    return json.loads(path.read_text(encoding='utf-8'))


def editor_formation(raw):
    from interop.message import CLASS_RANGES, parse_formation
    formation = deepcopy(raw)
    if 'formation' not in formation:
        formation['formation'] = {key: formation.pop(key) for key in
                                  ('formation_id', 'units', 'groups') if key in formation}
    units = formation['formation']['units']
    if any(u.get('robot_id') is None or u.get('platform_class') not in CLASS_RANGES
           for u in units):
        platforms, _, _, _ = parse_formation(formation)
        for unit, platform in zip(units, platforms):
            unit.update(robot_id=platform.robot_id, platform_class=platform.platform_class)
    return formation


def config_snapshot(bundle, report, run_id, sim_s):
    from workbench_target_editor import editor_target_slots, editor_targets
    formation = editor_formation(bundle['formation'])
    platforms = {p['robot_no']: p for p in report['platforms']}
    for unit in formation['formation']['units']:
        platform = platforms.get(unit.get('robot_id'))
        if platform is None:
            # A unit edited while the snapshot is written may not be in this
            # report yet; keep the configured pose instead of failing.
            continue
        unit['position'] = dict(zip(('x', 'y'), platform['pos']))
        unit['altitude_m'] = platform.get('z', unit.get('altitude_m', 0))
        unit['heading_rad'] = platform.get('yaw', unit.get('heading_rad', 0))
        unit['battery'] = platform.get('battery', unit.get('battery', 100))
        if not platform['alive']:
            unit['status'] = 'LOST'
    return dict(message=bundle['message'], formation=formation, run_id=run_id,
                sim_s=sim_s,
                completed=[j['job_id'] for j in report['jobs'] if j['status'] == 'succeeded'],
                excluded=[j['job_id'] for j in report['jobs'] if j['status'] == 'excluded'],
                targets=editor_targets(bundle['message']),
                target_slots=editor_target_slots())


def check_changed_tasks(scenario, slots, changed, completed, now, objective):
    """Reject infeasible edits before touching active commands."""
    by_task = {}
    for slot in slots:
        by_task.setdefault(slot.parent_task_id, []).append(slot)
    for task in scenario.tasks:
        if task.task_id not in changed:
            continue
        targets = [task.target, *(slot.target for slot in by_task[task.task_id])]
        for target in targets:
            for point in target_points(target):
                for zone in scenario.constraints:
                    if target_inside_no_go({'point': point}, [zone]):
                        label = zone.get('source') or zone.get('constraint_id') or '禁入区'
                        raise ValueError('%s 的点位 (%g, %g) 位于禁入区「%s」，请移到可通行区域'
                                         % (task.task_id, *point, label))
        if task.window_end_s <= now:
            raise ValueError('%s 的时间窗已经结束，请延长结束时间' % task.task_id)
        if any(dep not in completed for dep in task.depends_on):
            continue
        candidate = replace(task, depends_on=[], window_start_s=max(task.window_start_s, now))
        plan = Planner(replace(scenario, tasks=[candidate]), objective=objective).plan()
        if len({row.unit_id for row in plan.assignments}) < task.min_units:
            detail = plan.unassigned[0]['detail'] if plan.unassigned else '符合条件的平台不足'
            raise ValueError('%s 在当前状态下无法分配：%s' % (task.task_id, detail))


class LiveRun:
    def __init__(self, directory, scenario, tick_seconds=0.25, config=None):
        self.directory = directory
        self.scenario = scenario
        tasks = scenario['_meta']['interop']['message']['tasks']
        self.editable = all(is_editable_task(t) for t in tasks)
        self.tick_seconds = tick_seconds
        self.paused = False
        self.stop_requested = False
        self.revision = 0
        self.config = config or {}
        self.audit_count = 0

    def _snapshot(self, core, fleet, now):
        report = core.report()
        for row in report['platforms']:
            platform = core.platforms[row['pid']]
            state = fleet.platforms.get(row['pid'], {})
            row.update(pos=list(state.get('pos', platform.pos)),
                       yaw=state.get('yaw', platform.yaw),
                       battery=state.get('battery', platform.battery),
                       alive=platform.alive)
            if 'z' in state:
                row['z'] = state['z']
        config = config_snapshot(self.scenario['_meta']['interop'], report,
                                 self.directory.name, max(0, now - 1))
        from workbench_task_editor import editor_param_labels
        config.update(request=deepcopy(self.config), preset=self.config.get('scenario'),
            max_ticks=self.config.get('max_ticks'), param_labels=editor_param_labels())
        config['editable'] = self.editable
        config['task_types'] = editor_task_types()
        config['objective'] = core.custom_planner.objective
        config['deleted_task_ids'] = sorted(core.deleted_job_ids)
        by_pid = {pid_of(unit['robot_id']): unit['unit_id']
                  for unit in config['formation']['formation']['units']}
        config['occupied'] = [
            dict(task_id=command.job_id, unit_id=by_pid[command.worker_id],
                 end_s=max(command.expected_end_sim_s,
                           getattr(core, 'dynamic_ends', {}).get(command.command_id, 0)))
            for command in core.active.values() if command.worker_id in by_pid
        ]
        report.update(simulated_until_s=config['sim_s'], avoid=fleet.nav is not None,
                      behavior=fleet._behavior_on(),
                      **{key: self.config[key] for key in ('mode', 'motion')
                         if key in self.config})
        return dict(config=config, paused=self.paused, stopping=self.stop_requested, revision=self.revision,
                    report=report, scene_jobs=self.scenario['jobs'],
                    audit_count=self.audit_count,
                    jobs=[dict(id=j['job_id'], status=j['status'],
                               progress=j['progress'], work=j['work'])
                          for j in report['jobs']],
                    assignments=[dict(id=c.job_id, platform=c.worker_id)
                                 for c in core.active.values()])

    def _apply(self, payload, core, fleet, now):
        if not self.editable:
            raise ValueError('该场景支持实时查看、暂停和继续，配置为只读')
        if (not self.paused or payload.get('revision') != self.revision
                or payload.get('sim_s') != max(0, now - 1)):
            raise ValueError('请先暂停仿真并重新读取当前配置')
        tasks, units = payload.get('tasks'), payload.get('units')
        if not isinstance(tasks, list) or len(tasks) > 50:
            raise ValueError('本轮最多可包含 50 项任务')
        if not isinstance(units, list) or not all(isinstance(u, dict) for u in units):
            raise ValueError('平台配置格式无效')
        if not all(is_editable_task(t) for t in tasks):
            raise ValueError('实时编辑支持五类演示任务')
        if 'targets' in payload:
            from workbench_target_editor import apply_targets
            tasks = apply_targets(tasks, payload['targets'],
                                  skip_task_ids=core.succeeded_at)
        bundle = self.scenario['_meta']['interop']
        old_tasks = {t['task_id']: t for t in bundle['message']['tasks']}
        incoming = {t.get('task_id'): t for t in tasks}
        if len(incoming) != len(tasks):
            raise ValueError('任务编号不能重复')
        delete_tasks = payload.get('delete_tasks', [])
        if not isinstance(delete_tasks, list) or any(not isinstance(jid, str) for jid in delete_tasks):
            raise ValueError('删除任务列表格式无效')
        deleted = set(delete_tasks)
        if deleted != old_tasks.keys() - incoming.keys():
            raise ValueError('请通过删除按钮移除任务，已有任务编号保持不变')
        if deleted & core.succeeded_at.keys():
            raise ValueError('已完成的任务保留在本轮记录中')
        if incoming.keys() & core.deleted_job_ids:
            raise ValueError('本轮已删除的任务编号不能重复使用')
        previously_excluded = {jid for jid, job in core.jobs.items() if job.status == 'excluded'}
        exclude_tasks = payload.get('exclude_tasks', sorted(previously_excluded - deleted))
        if not isinstance(exclude_tasks, list) or any(not isinstance(jid, str) for jid in exclude_tasks):
            raise ValueError('未纳入任务列表格式无效')
        excluded = set(exclude_tasks)
        if not excluded <= incoming.keys() or excluded & core.succeeded_at.keys():
            raise ValueError('只能取消纳入本轮中未完成的现有任务')
        for jid in core.succeeded_at:
            incoming[jid] = old_tasks[jid]
        for jid, task in incoming.items():
            deps = task.get('depends_on', task.get('prerequisites', []))
            if isinstance(deps, list):
                removed_deps = [dep for dep in deps if isinstance(dep, str) and dep in deleted]
                if removed_deps:
                    raise ValueError('%s 仍依赖 %s，请先修改前置任务或一并删除'
                                     % (jid, '、'.join(removed_deps)))
        base = self._snapshot(core, fleet, now)['config']
        old_units = {u['robot_id']: u for u in base['formation']['formation']['units']}
        if not 1 <= len(units) <= 50:
            raise ValueError('本轮须保留 1 至 50 台平台')
        new_units = {u.get('robot_id'): u for u in units}
        if any(isinstance(no, bool) or not isinstance(no, int) for no in new_units):
            raise ValueError('每台平台都要填写机器人编号')
        if len(new_units) != len(units):
            raise ValueError('平台机器人编号不能重复')
        added = sorted(set(new_units) - set(old_units))
        removed = sorted(set(old_units) - set(new_units))
        for no, row in new_units.items():
            old = old_units.get(no)
            if old is None:
                continue        # 新增平台由 parse_message 校验编号范围与类别
            if row.get('platform_class') != old['platform_class']:
                raise ValueError('实时编辑中请保留平台类别')
            if row.get('unit_id') != old.get('unit_id'):
                raise ValueError('实时编辑中请保留平台编号')
            if old.get('status') == 'LOST' and row.get('status') != 'LOST':
                raise ValueError('失联平台保留失联状态')

        message = dict(bundle['message'], tasks=list(incoming.values()))
        for key in ('observation_targets', 'target_library'):
            if key in payload:
                message[key] = payload[key]
        formation = deepcopy(base['formation'])
        formation['formation']['units'] = units
        parsed = parse_message(message, formation, allow_empty_tasks=True)
        slots = decompose(parsed)
        updated = to_v2_dict(parsed, message, formation)
        check_scenario_v2(updated, allow_empty_jobs=True)
        proposed_planner = type(core.custom_planner)(
            parsed, objective=core.custom_planner.objective, data=updated)
        if not fleet._behavior_on() and any(
                j.get('_behavior', {}).get('_configured_kind') for j in updated['jobs']):
            raise ValueError('本轮需启用逐步运动与到位行为，才能添加配置动作')
        candidates = {j.job_id: j for j in build_jobs(updated)}
        changed = {jid for jid, task in incoming.items() if task != old_tasks.get(jid)}
        previous_targets = {row['target_id']: row for row in bundle['message'].get('target_library', [])}
        new_targets = {row['target_id']: row for row in message.get('target_library', [])}
        changed.update(jid for jid, task in incoming.items() if jid not in core.succeeded_at
                       and any(previous_targets.get(ident) != new_targets.get(ident)
                               for ident in task['params'].get('target_library_ids', [])))
        selection_changed = (excluded ^ previously_excluded) - deleted
        check_changed_tasks(parsed, slots, (changed | selection_changed) - excluded,
                            core.succeeded_at, now, core.custom_planner.objective)
        platform_by_no = {p.robot_no: p for p in core.platforms.values()}
        old_specs = {p.robot_id: p for p in parse_message(
            bundle['message'], base['formation'], allow_empty_tasks=True).platforms}
        new_specs = {p.robot_id: p for p in parsed.platforms}
        modified = {platform_by_no[no].pid for no in new_units
                    if no in old_units and old_specs[no] != new_specs[no]}
        removed_pids = {pid_of(no) for no in removed}
        affected = changed | selection_changed | deleted
        stopping = [c for c in core.active.values()
                    if c.job_id in affected or c.worker_id in modified
                    or c.worker_id in removed_pids]
        interrupted_commands = [c.command_id for c in stopping]
        interrupted = {c.job_id for c in stopping}
        from workbench_patrol_editor import check_task_drafts, POINT_PARAMS, POINT_LIST_PARAMS
        geometry_keys = set(POINT_PARAMS) | set(POINT_LIST_PARAMS) | {
            'search_starts', 'gates', 'positions', 'withdraw', 'sensor_radius_m',
            'radius', 'objective_radius', 'observe_radius', 'staging_radius'}
        def geometry(task):
            return (task.get('target'), {key: task.get('params', {}).get(key) for key in geometry_keys})
        geometry_changed = {jid for jid in changed if jid not in old_tasks
                            or geometry(incoming[jid]) != geometry(old_tasks[jid])}
        occupied = [row for row in base['occupied'] if row['task_id'] not in interrupted]
        check_task_drafts(parsed, (changed | selection_changed) - excluded,
                            core.custom_planner.objective, now=now, occupied=occupied,
                            completed=core.succeeded_at, excluded=excluded,
                            geometry_task_ids=geometry_changed)

        # The local fleet acknowledges cancellation synchronously before new dispatch.
        core.advance(now)
        cancel_plan_id = core.plan.plan_id if core.plan is not None else max(0, core.plan_id - 1)
        if interrupted or removed_pids:
            core.plan = None
        if interrupted:
            for jid in interrupted:
                core.jobs[jid].status = 'cancelling'
                core.jobs[jid]._configuration_cancel = True
            commands = [c.to_wire(core.run_id, cancel_plan_id) for c in core._dispatch(now)]
            for event in fleet.submit(commands, now):
                core.receive(event, now)
        for jid in (changed | selection_changed | interrupted) - deleted:
            if jid not in core.succeeded_at:
                job = candidates[jid]
                if jid in core.jobs:
                    job.attempts = core.jobs[jid].attempts
                if jid in excluded:
                    job.status = 'excluded'
                core.jobs[jid] = job
        for jid in deleted:
            core.jobs.pop(jid)
            core.job_cmds.pop(jid, None)
        core.deleted_job_ids.update(deleted)
        for no, row in new_units.items():
            if no not in old_units or pid_of(no) not in modified:
                continue
            platform = platform_by_no[no]
            platform.pos = (float(row['position']['x']), float(row['position']['y']))
            platform.yaw = float(row['heading_rad'])
            old_state = fleet.platforms.get(platform.pid)
            if old_state is not None:
                old_state.update(pos=platform.pos, yaw=platform.yaw, z=float(row['altitude_m']),
                                 disabled=row['status'] != 'READY')
                fleet.return_state.pop(platform.pid, None)
            else:
                # Keep the original return location for dispatched platforms.
                fleet.platforms[platform.pid] = dict(pos=platform.pos, yaw=platform.yaw, z=float(row['altitude_m']), battery=platform.battery, ammo=platform.ammo, active=False, dead=False)
        if added:
            from contracts_v2 import build_platforms
            units_by_no = {p.robot_id: p for p in parsed.platforms}
            for platform in build_platforms(updated):
                if platform.robot_no not in added:
                    continue
                unit = units_by_no[platform.robot_no]
                platform.speed, platform.work_rate = unit.speed_mps, unit.work_rate
                platform.payload, platform.sensor = unit.payload, unit.sensor
                platform.battery = unit.battery
                platform.can_climb = unit.is_air
                core.platforms[platform.pid] = platform
                core.energy_capacity[platform.pid] = float(platform.battery)
                fleet.home[platform.pid] = platform.pos
                fleet.platforms[platform.pid] = dict(pos=platform.pos, yaw=unit.heading_rad,
                    z=unit.altitude_m, battery=platform.battery, ammo=platform.ammo,
                    active=False, dead=False, disabled=unit.status != 'READY',
                    return_profile=dict(can_climb=unit.is_air, speed=platform.speed,
                                        move_cost=platform.move_cost, kind=platform.kind))
        for pid in removed_pids:
            core.platforms.pop(pid, None)
            core.energy_capacity.pop(pid, None)
            core.platform_cmd.pop(pid, None)
            fleet.platforms.pop(pid, None)
            fleet.home.pop(pid, None)
            fleet.return_state.pop(pid, None)
        core.custom_planner.scenario = parsed
        core.custom_planner._cached_interop_plan = None
        core.custom_planner.data = self.scenario
        if hasattr(core.custom_planner, "refresh_subtasks"):
            core.custom_planner.refresh_subtasks()
        core.custom_planner.activation_rules = proposed_planner.activation_rules
        handoffs = getattr(core, '_interop_handoffs', {})
        for jid in changed | selection_changed | deleted:
            handoffs.pop(jid, None)
        self.scenario['jobs'] = updated['jobs']
        self.scenario['_meta'].pop('observation_targets', None)
        if 'observation_targets' in updated['_meta']:
            self.scenario['_meta']['observation_targets'] = updated['_meta']['observation_targets']
        fleet.interop_jobs = {j['job_id'] for j in updated['jobs']}
        fleet.behavior_params = {j['job_id']: j.get('_behavior', {}) for j in updated['jobs']}

        bundle.update(message=message, formation=formation)
        core.pending.append(('config_updated', '工作台配置更新'))
        self.revision += 1
        core.record('config_updated', revision=self.revision,
                    interrupted_commands=interrupted_commands,
                    config_changed=bool(changed or selection_changed or deleted or added or removed or modified), jobs=sorted(changed | selection_changed),
                    platforms=sorted(modified), restarted=sorted(interrupted - deleted),
                    added_platforms=sorted(added), removed_platforms=sorted(removed),
                    deleted=sorted(deleted), excluded=sorted(excluded),
                    message=message, formation=formation)
        # Persist the applied edit at the last completed tick, for later replay.
        from workbench_replay_editor import SEED_FILE
        seed_path = self.directory / SEED_FILE
        if getattr(self, 'persist_history', True) and seed_path.is_file():
            seed = read_json(seed_path)
            changes = {key: deepcopy(payload[key]) for key in ('tasks','units','targets','delete_tasks','exclude_tasks') if key in payload}
            seed['history'].append(dict(at_s=max(0, now - 1), changes=changes))
            write_json(seed_path, seed)
        self.paused = False

    def __call__(self, core, fleet, now):
        state_file = self.directory / '.live_state.json'
        request_file = self.directory / '.live_request.json'
        if not (self.directory / '.live_scene.json').exists():
            write_json(self.directory / '.live_scene.json', self.scenario)
        snapshot = self._publish(core, fleet, now, state_file)
        deadline = time.monotonic() + self.tick_seconds
        while self.paused or time.monotonic() < deadline:
            if request_file.is_file():
                request = read_json(request_file)
                error = None
                try:
                    if request['action'] == 'pause':
                        self.paused = True
                    elif request['action'] == 'resume':
                        self.paused = False
                    elif request['action'] == 'stop':
                        self.stop_requested = True
                        self.paused = False
                    else:
                        self._apply(request, core, fleet, now)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    error = str(exc)
                snapshot = self._publish(core, fleet, now, state_file)
                request_file.unlink()
                write_json(self.directory / '.live_reply.json',
                           dict(id=request['id'], error=error, state=snapshot))
                if self.stop_requested:
                    break
            time.sleep(0.04)
        return False if self.stop_requested else None

    def _publish(self, core, fleet, now, state_file):
        if getattr(self, '_published_scene_revision', None) != self.revision:
            write_json(self.directory / '.live_scene.json', self.scenario)
            self._published_scene_revision = self.revision
        if len(core.audit) > self.audit_count:
            with (self.directory / '.live_trace.jsonl').open('a', encoding='utf-8') as stream:
                for row in core.audit[self.audit_count:]:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            self.audit_count = len(core.audit)
        snapshot = self._snapshot(core, fleet, now)
        write_json(state_file, snapshot)
        return snapshot
