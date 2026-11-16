# -*- coding: utf-8 -*-
"""Red-side targets shown in the workbench's 目标配置 panel.

The 4.1 message keeps targets inside task ``params`` (and, for T-ASL, inside
``task.target``). The editor exposes them as their own section, but the stored
shape stays byte-for-byte the one the planner and the behavior layer already
read, so planning/execution don't change:

  * T-RCN  ``params.tracking_target`` / ``params.relay_target``
  * T-PTL  ``params.observation_target``
  * T-SEC  ``params.intruders[]``
  * T-ASL  ``task.target.<point|key_point|target_list>`` +
           ``params.target_id`` / ``params.object_label``

``editor_targets()`` flattens those into one list for the panel;
``apply_targets()`` writes an edited list back into the task messages.
"""
from copy import deepcopy
import math

from interop.message import ASL_POINT_TARGETS
from workbench_task_editor import PARAM_LABELS


_TARGET_KINDS = ('point', 'key_point', 'target_list')

SLOTS = {
    'tracking': dict(
        label='跟踪目标', task_types=('T-RCN',), param='tracking_target',
        multi=False, deletable=True,
        help='侦察区内出现、驶向区外。可等待跟踪平台建立接触再移动。',
        fields=('target_id', 'start', 'goal', 'speed_mps', 'move_after_s',
                'track_outside_s', 'track_until_stop', 'move_after_contact',
                'stop_orbit_s'),
        defaults={'target_id': '', 'speed_mps': 3, 'move_after_s': 0,
                  'track_outside_s': 20, 'track_until_stop': True,
                  'move_after_contact': True, 'stop_orbit_s': 18}),
    'observation': dict(
        label='观察目标', task_types=('T-PTL',), param='observation_target',
        multi=False, deletable=True, help='巡逻警戒中需要跟踪上报的移动目标',
        fields=('target_id', 'start', 'goal', 'speed_mps'),
        defaults={'target_id': '', 'speed_mps': 2}),
    'relay': dict(
        label='接力目标', task_types=('T-RCN',), param='relay_target',
        multi=False, deletable=True,
        help='接力场景的同一目标；由 RCN 任务交接给后续任务',
        fields=('target_id', 'start', 'goal', 'speed_mps'),
        defaults={'target_id': '', 'speed_mps': 2}),
    'intruder': dict(
        label='闯入目标', task_types=('T-SEC',), param='intruders',
        multi=True, deletable=True,
        help='出场计时起点由任务的「目标出场方式」决定。',
        fields=('target_id', 'start', 'goal', 'speed_mps', 't_start_s',
                'authorized', 'compliance'),
        defaults={'target_id': '', 'speed_mps': 2.5, 't_start_s': 0,
                  'authorized': False, 'compliance': True}),
    'assault': dict(
        label='突击目标点', task_types=('T-ASL',), param=None,
        multi=False, deletable=False,
        help='机动突击的打击目标点；由任务本身派生，不能删除',
        fields=('target_id', 'object_label', 'point'),
        defaults={'target_id': '', 'object_label': ''}),
}

FIELD_KINDS = {
    'target_id': 'text', 'object_label': 'text',
    'start': 'point', 'goal': 'point', 'point': 'point',
    'speed_mps': 'number', 'move_after_s': 'number',
    'track_outside_s': 'number', 't_start_s': 'number',
    'authorized': 'bool', 'compliance': 'bool',
    'track_until_stop': 'bool', 'move_after_contact': 'bool',
    'stop_orbit_s': 'number',
}

_TRACK_SWITCHES = ('track_until_stop', 'move_after_contact')


def _field_specs(slot):
    entry = SLOTS[slot]
    return [dict(key=key, kind=FIELD_KINDS.get(key, 'text'),
                 label=PARAM_LABELS.get(key, key))
            for key in entry['fields']]


def editor_target_slots():
    """Slot catalog for the editor (labels, task types, field widgets, defaults)."""
    out = {}
    for name, entry in SLOTS.items():
        out[name] = dict(
            label=entry['label'], help=entry['help'],
            task_types=list(entry['task_types']),
            multi=entry['multi'], deletable=entry['deletable'],
            fields=_field_specs(name),
            defaults=deepcopy(entry['defaults']),
        )
    return out


def _number(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('%s必须是数字' % name)
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('%s必须是有限数' % name)
    if minimum is not None and value < minimum:
        raise ValueError('%s不能小于%g' % (name, minimum))
    return value


def _point(value, name):
    if isinstance(value, dict) and 'x' in value and 'y' in value:
        value = [value['x'], value['y']]
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('%s必须是 [x, y] 坐标' % name)
    return [_number(value[0], name + ' X'), _number(value[1], name + ' Y')]


def _text(value, name):
    if not isinstance(value, str):
        raise ValueError('%s必须是文本' % name)
    return value.strip()


def _bool(value, name):
    if not isinstance(value, bool):
        raise ValueError('%s必须是布尔值' % name)
    return value


def _clean_target(slot, entry, base=None):
    """Normalize one panel entry into the stored 4.1 target shape."""
    spec = SLOTS[slot]
    # Target dictionaries can carry planner fields newer than this panel.
    # Preserve those fields when an existing row is round-tripped.
    out = deepcopy(base) if isinstance(base, dict) else {}
    for key in spec['fields']:
        label = PARAM_LABELS.get(key, key)
        value = entry.get(key, False if key in _TRACK_SWITCHES
                          else spec['defaults'].get(key))
        if key in ('start', 'goal', 'point'):
            if value is None:
                raise ValueError('%s需要填写坐标' % label)
            out[key] = _point(value, label)
        elif FIELD_KINDS.get(key) == 'bool':
            if value is None:
                raise ValueError('%s需要填写' % label)
            out[key] = _bool(value, label)
        elif key == 'target_id':
            out[key] = _text(value, label)
            if not out[key] and slot != 'assault':
                raise ValueError('目标编号不能为空')
        elif key == 'object_label':
            out[key] = _text(value, label)
        else:
            minimum = 0.0
            if key in ('speed_mps', 'track_outside_s'):
                minimum = 1e-9
            if value is None:
                raise ValueError('%s需要填写数字' % label)
            out[key] = _number(value, label, minimum)
    return out


def editor_targets(message):
    """Flatten a 4.1 message's red targets into panel entries.

    Malformed legacy params are skipped rather than raising: the editor must
    still open for historical runs.
    """
    tasks = message.get('tasks') if isinstance(message, dict) else None
    if not isinstance(tasks, list):
        return []
    targets = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = task.get('task_id')
        task_type = task.get('task_type')
        params = task.get('params') or {}
        if not isinstance(task_id, str) or not isinstance(params, dict):
            continue
        for name, spec in SLOTS.items():
            if task_type not in spec['task_types']:
                continue
            if name == 'assault':
                target = task.get('target') or {}
                kinds = [key for key in target if key in _TARGET_KINDS]
                if len(kinds) != 1:
                    continue
                kind = kinds[0]
                value = target[kind]
                if kind == 'target_list':
                    points = value if isinstance(value, list) else []
                    point = points[0] if points else None
                else:
                    point = value
                try:
                    point = _point(point, '突击目标点')
                except ValueError:
                    point = [0, 0]
                entry = dict(slot=name, task_id=task_id, kind=kind,
                             target_id=str(params.get('target_id') or ''),
                             object_label=str(params.get('object_label') or ''),
                             point=point)
                targets.append(entry)
            elif spec['multi']:
                values = params.get(spec['param']) or []
                if not isinstance(values, list):
                    continue
                for index, item in enumerate(values):
                    if not isinstance(item, dict):
                        continue
                    entry = {key: deepcopy(item.get(key, spec['defaults'].get(key)))
                             for key in spec['fields']}
                    entry.update(slot=name, task_id=task_id, index=index)
                    targets.append(entry)
            else:
                item = params.get(spec['param'])
                if not isinstance(item, dict):
                    continue
                entry = {key: deepcopy(item.get(key, spec['defaults'].get(key)))
                         for key in spec['fields']}
                if name == 'tracking':
                    entry.update((key, item.get(key, False))
                                 for key in _TRACK_SWITCHES)
                entry.update(slot=name, task_id=task_id)
                targets.append(entry)
    return targets


def _clear_slots(task):
    params = task.get('params')
    if not isinstance(params, dict):
        params = task['params'] = {}
    for name, spec in SLOTS.items():
        if task.get('task_type') not in spec['task_types']:
            continue
        if name == 'assault':
            continue
        params.pop(spec['param'], None)


def apply_targets(tasks, targets, skip_task_ids=()):
    """Write edited red targets back into a deep copy of ``tasks``.

    Every slot is authoritative: parameters for slots that no longer have an
    entry are removed, so deleting a target in the panel really disables it.
    Completed tasks listed in ``skip_task_ids`` keep their parameters.
    """
    if not isinstance(tasks, list):
        raise ValueError('任务配置格式无效')
    if targets is None:
        targets = []
    if not isinstance(targets, list):
        raise ValueError('红方目标配置格式无效')
    skip = set(skip_task_ids or ())
    edited = [deepcopy(task) for task in tasks]
    by_id = {}
    existing = {}
    for task in edited:
        task_id = task.get('task_id') if isinstance(task, dict) else None
        if not isinstance(task_id, str) or not task_id:
            continue
        by_id[task_id] = task
        params = task.get('params')
        if not isinstance(params, dict):
            continue
        for name, spec in SLOTS.items():
            if task.get('task_type') not in spec['task_types']:
                continue
            if spec['param']:
                existing[(task_id, name)] = deepcopy(params.get(spec['param']))
    for task in edited:
        if isinstance(task, dict) and task.get('task_id') not in skip:
            _clear_slots(task)

    seen = {}
    for entry in targets:
        if not isinstance(entry, dict):
            raise ValueError('红方目标必须是对象')
        slot = entry.get('slot')
        task_id = entry.get('task_id')
        if slot not in SLOTS:
            raise ValueError('红方目标用途无效：%r' % (slot,))
        if not isinstance(task_id, str) or not task_id:
            raise ValueError('红方目标缺少所属任务')
        task = by_id.get(task_id)
        if task is None:
            raise ValueError('红方目标关联的任务 %s 不在本轮配置中' % task_id)
        spec = SLOTS[slot]
        if task.get('task_type') not in spec['task_types']:
            raise ValueError('%s（%s）不支持%s'
                             % (task_id, task.get('task_type'), spec['label']))
        if task_id in skip:
            continue
        params = task.get('params')
        if not isinstance(params, dict):
            params = task['params'] = {}
        prior = existing.get((task_id, slot))
        if spec['multi']:
            values = prior
            index = entry.get('index')
            base = (values[index]
                    if isinstance(values, list) and isinstance(index, int)
                    and 0 <= index < len(values) else None)
        else:
            base = prior if isinstance(prior, dict) else None
        cleaned = _clean_target(slot, entry, base)
        if (slot == 'tracking' and isinstance(base, dict)
                and base.get('target_id') == cleaned['target_id']):
            # A legacy tracking target that predates these switches stays on
            # the legacy timing semantics until the operator explicitly turns
            # a switch on. This keeps an open/save round trip lossless.
            for option in _TRACK_SWITCHES:
                if option not in base and not cleaned[option]:
                    cleaned.pop(option, None)
            if ('stop_orbit_s' not in base
                    and cleaned['stop_orbit_s'] == spec['defaults']['stop_orbit_s']):
                cleaned.pop('stop_orbit_s', None)
        if slot == 'assault':
            kind = entry.get('kind')
            if kind is None:
                existing = [key for key in (task.get('target') or {})
                            if key in ASL_POINT_TARGETS]
                if len(existing) != 1:
                    raise ValueError('%s 的突击目标形状无效' % task_id)
                kind = existing[0]
            elif kind not in ASL_POINT_TARGETS:
                raise ValueError('%s 的突击目标形状必须是 point/key_point/target_list'
                                 % task_id)
            value = cleaned['point']
            target = {kind: [value] if kind == 'target_list' else value}
            task['target'] = target
            params['target_id'] = cleaned['target_id']
            params['object_label'] = cleaned['object_label']
            continue
        key = (slot, task_id)
        if spec['multi']:
            params.setdefault(spec['param'], []).append(cleaned)
        else:
            if key in seen:
                raise ValueError('%s 只能有一个%s' % (task_id, spec['label']))
            seen[key] = True
            params[spec['param']] = cleaned
    return edited
