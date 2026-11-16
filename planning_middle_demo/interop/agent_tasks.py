"""Human-facing per-platform projection of saved plans; never infer execution."""
import csv
import io
import json
import re


ARTIFACT_NAMES = ('agent_tasks.md', 'agent_tasks.csv', 'agent_tasks.json')
NOTE = ('以下为保存的计划快照，不是实际执行时序；运行中可能重规划。'
        '时序为各平台计划作业起止，start_s 已含到达耗时；时间单位秒。'
        '未记录的约束不推定为无约束；未分配槽位单独列出。')


def number_key(value):
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r'(\d+)', str(value))]


def build_agent_tasks(plan, platforms=()):
    """Accept JSON so historical runs can use their own saved plan as evidence."""
    agents = {}
    for p in platforms:
        unit = p.get('unit_id') or p.get('id')
        if not unit:
            continue
        agents[unit] = dict(unit_id=unit, robot_id=p.get('robot_id'),
                            platform_class=p.get('platform_class'), tasks=[])
    for a in plan.get('assignments') or []:
        unit = a.get('unit_id')
        agent = agents.setdefault(unit, dict(unit_id=unit, robot_id=a.get('robot_id'),
                                             platform_class=None, tasks=[]))
        if agent.get('robot_id') is None:
            agent['robot_id'] = a.get('robot_id')
        # Preserve source fields, including unknown historical values.
        agent['tasks'].append({key: a.get(key) for key in (
            'subtask_id', 'parent_task_id', 'task_type', 'role', 'start_s',
            'end_s', 'travel_s', 'window', 'depends_on', 'coordination', 'status',
            'runtime_plan_id', 'attempt', 'command_id')})
    ordered = sorted(agents.values(), key=lambda p: (
        not bool(p['tasks']), number_key('rover_%02d' % int(p['robot_id'])
                                       if p.get('robot_id') is not None else p['unit_id'])))
    for agent in ordered:
        robot = agent['robot_id']
        agent['platform_id'] = 'rover_%02d' % int(robot) if robot is not None else None
        agent['participates'] = bool(agent['tasks'])
        agent['tasks'].sort(key=lambda a: (a.get('start_s') or 0,
                                           a.get('end_s') or 0,
                                           number_key(a.get('subtask_id'))))
        for index, task in enumerate(agent['tasks'], 1):
            task['sequence'] = index
            task['transit_start_s'] = (round(task['start_s'] - task['travel_s'], 3)
                                       if task['start_s'] is not None and task['travel_s'] is not None else None)
            task['coordination_peers'] = [dict(unit_id=a.get('unit_id'), subtask_id=a.get('subtask_id'))
                for a in plan.get('assignments') or []
                if 'simultaneous_arrival' in (task.get('coordination') or [])
                and 'simultaneous_arrival' in (a.get('coordination') or [])
                and a.get('parent_task_id') == task['parent_task_id']
                and a.get('runtime_plan_id') == task.get('runtime_plan_id')
                and a.get('attempt') == task.get('attempt')
                and a.get('subtask_id') != task['subtask_id']]
    return dict(plan_id=plan.get('plan_id'), note=NOTE, agents=ordered,
                unassigned=plan.get('unassigned') or [],
                conflicts=plan.get('conflicts') or [])


def _text(value):
    if value is None:
        return '未记录'
    if isinstance(value, list):
        return '；'.join(str(v) for v in value) if value else '无显式条目'
    return str(value)


def render_agent_tasks(data, heading_level=1):
    heading = '#' * heading_level
    section = '#' * (heading_level + 1)
    lines = [heading + ' 单平台智能体任务清单', '', data['note'], '',
             '同步到达 simultaneous_arrival：同父任务的协同槽位使用不同平台、开始时刻对齐（校验容差 0.001 s）；handover：交接标记。'
             '其他约束保留原编码，具体执行支持以规划器和运行层为准。', '']
    for agent in data['agents']:
        if not agent['tasks']:
            continue
        lines += [section + ' %s · %s' % (agent['unit_id'], agent['platform_id'] or '机器人编号未记录'), '']
        lines += ['| 顺序 | 子任务 / 父任务 | 类型 / 角色 | 机动起点 → 作业开始 → 结束 / s | 时间窗口 / s | 前置子任务 | 协同约束 / 同组成员 |',
                  '| ---: | --- | --- | --- | --- | --- | --- |']
        for t in agent['tasks']:
            window = t.get('window') or {}
            binding = (' [计划 %s / 尝试 %s]' % (t['runtime_plan_id'], t['attempt'])
                       if t.get('runtime_plan_id') is not None else '')
            cells = [t['sequence'], '%s / %s%s' % (t['subtask_id'], t['parent_task_id'], binding),
                     '%s / %s' % (t['task_type'], t.get('role') or '—'),
                     '%s → %s → %s' % (_text(t['transit_start_s']), _text(t['start_s']), _text(t['end_s'])),
                     '%s → %s' % (_text(window.get('start_s')), _text(window.get('end_s'))),
                     _text(t['depends_on']), _text(t['coordination']) +
                     (' / 同组：' + '；'.join('%s:%s' % (p['unit_id'],p['subtask_id']) for p in t['coordination_peers']) if t['coordination_peers'] else '')]
            lines.append('| ' + ' | '.join(str(c).replace('|', '\\|').replace('\n', ' ') for c in cells) + ' |')
        lines.append('')
    idle = [a for a in data['agents'] if not a['tasks']]
    if idle:
        lines += [section + ' 本计划未分配子任务的平台', '',
                  '、'.join('%s（%s）' % (a['unit_id'],a['platform_id'] or '机器人编号未记录') for a in idle), '']
    lines += [section + ' 未分配子任务与计划冲突', '',
              '未分配：' + json.dumps(data['unassigned'], ensure_ascii=False), '',
              '冲突：' + json.dumps(data['conflicts'], ensure_ascii=False), '']
    return '\n'.join(lines)


def agent_artifact(data, name):
    if name == 'agent_tasks.md':
        return render_agent_tasks(data).encode('utf-8')
    if name == 'agent_tasks.json':
        return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    if name != 'agent_tasks.csv':
        raise ValueError('Unknown agent artifact')
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['unit_id', 'platform_id', 'robot_id', 'sequence', 'subtask_id',
                     'parent_task_id', 'task_type', 'role', 'start_s', 'end_s',
                     'window_start_s', 'window_end_s', 'depends_on', 'coordination', 'status',
                     'transit_start_s', 'coordination_peers', 'runtime_plan_id', 'attempt', 'command_id'])
    for agent in data['agents']:
        for t in agent['tasks'] or [{}]:
            window = t.get('window') or {}
            writer.writerow([agent['unit_id'], agent['platform_id'], agent['robot_id'],
                             t.get('sequence'), t.get('subtask_id'), t.get('parent_task_id'),
                             t.get('task_type'), t.get('role'), t.get('start_s'), t.get('end_s'),
                             window.get('start_s'), window.get('end_s'),
                             _text(t.get('depends_on')), _text(t.get('coordination')),
                             t.get('status', 'NO_ASSIGNMENT'), t.get('transit_start_s'),
                             json.dumps(t.get('coordination_peers', []), ensure_ascii=False),
                             t.get('runtime_plan_id'), t.get('attempt'), t.get('command_id')])
    return output.getvalue().encode('utf-8-sig')
