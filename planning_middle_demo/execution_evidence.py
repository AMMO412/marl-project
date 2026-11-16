"""Bind emitted runtime plans to actual commands and task-only replay windows."""
import copy
import math


def bind_execution(history, audit, end_s, objective):
    versions = {v['runtime_plan_id']: v for v in history}
    finishes = {}
    terminal_status = {}
    for row in audit:
        if row.get('kind') == 'attempt_finished':
            finishes.setdefault(row['command_id'], row['sim_s'])
        if row.get('kind') == 'command_abandoned':
            finishes.setdefault(row['command_id'], row['sim_s'])
            terminal_status[row['command_id']] = row.get('reason', 'abandoned')
        if row.get('kind') == 'feedback_applied':
            e = row.get('event') or {}
            if e.get('status') in ('succeeded', 'failed', 'cancelled'):
                terminal_status[e['command_id']] = e['status']
    bindings, assignments, intervals = [], [], {}
    for event in audit:
        if event.get('kind') != 'job_dispatched':
            continue
        version = versions.get(event.get('plan_id'))
        if version is None:
            raise ValueError('实际下发缺少对应规划版本: %s' % event.get('plan_id'))
        job_id = event['job_id']
        commands = {c['worker_id']: c['command_id'] for c in event['commands']}
        candidates = [a for a in version['plan'].get('assignments') or []
                      if a.get('parent_task_id') == job_id
                      and 'rover_%02d' % a['robot_id'] in commands]
        represented = {'rover_%02d' % a['robot_id'] for a in candidates}
        if represented != set(event['pids']):
            raise ValueError('规划版本与实际下发成员不一致: %s' % job_id)
        binding = dict(plan_id=event['plan_id'], job_id=job_id,
            attempt=event['attempt'], issued_s=event['sim_s'],
            planned_start_s=event['planned_start'], planned_end_s=event['planned_end'],
            commands=[], subtask_ids=[a['subtask_id'] for a in candidates])
        for pid, cid in commands.items():
            finish = min(float(finishes.get(cid, end_s)), float(end_s))
            status = terminal_status.get(cid, 'member_lost' if cid in finishes else 'in_progress')
            command = dict(worker_id=pid, command_id=cid,
                           start_s=event['sim_s'], end_s=finish, status=status)
            binding['commands'].append(command)
            intervals.setdefault(pid, []).append(command)
        bindings.append(binding)
        for item in candidates:
            a = copy.deepcopy(item)
            pid = 'rover_%02d' % a['robot_id']
            a.update(runtime_plan_id=event['plan_id'], attempt=event['attempt'],
                     command_id=commands[pid], issued_s=event['sim_s'])
            assignments.append(a)
    metrics = dict(objective=objective,
        makespan_s=max((b['planned_end_s'] for b in bindings), default=None),
        total_energy=round(sum(a.get('energy') or 0 for a in assignments), 3),
        total_exposure=round(sum(a.get('risk') or 0 for a in assignments), 3))
    metrics['detection_probability'] = round(1-math.exp(-.1*metrics['total_exposure']), 4)
    complete = bool(bindings) and all(c['status'] == 'succeeded' for b in bindings for c in b['commands'])
    return dict(schema='runtime-planning-evidence/v1',
        plan_id='DISPATCHED-RUNTIME-PLAN', objective=objective,
        source='runtime_dispatch', generated_versions=len(history),
        note='来自实际下发的动态规划版本；每个槽位绑定计划版本、任务尝试和指令。计划为该尝试的全程估计，执行仅统计同次尝试的实际轨迹；整轮（含返航）另列。失败/取消/未完成尝试不作为完整执行差值。',
        assignments=assignments, bindings=bindings, metrics=metrics,
        comparison_complete=complete, intervals=intervals)
