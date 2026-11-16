"""Colleague cases adapted to the current planner's established model units.

Keep the supplied physical profiles in the archived input. This adapter does
not replace the project's capability gates with a different matching policy.
"""
from copy import deepcopy

CASES = {
    'interop_integrated': ('五类任务综合案例（六栋楼 · 20台）', 700, False),
    'interop_campus_motion20': ('六栋楼综合运动案例（9任务 · 20台）', 1100, True),
}


def adapt_inputs(message, formation):
    from interop.message import CLASS_BASE_PROFILE, CLASS_CAPABILITIES
    message, formation = deepcopy(message), deepcopy(formation)
    for unit in formation['formation']['units']:
        profile = CLASS_BASE_PROFILE[unit['platform_class']]
        # Preserve the explicit source values alongside established model fields.
        unit['_source_profile'] = {key: deepcopy(unit[key]) for key in
            ('payload_kg', 'sensor', 'motion') if key in unit}
        unit.setdefault('payload', profile['payload'])
        unit.pop('motion', None)
        unit.pop('payload_kg', None)
        if isinstance(unit.get('sensor'), dict):
            unit['sensor'] = unit['sensor']['type']
        unit.setdefault('capabilities', deepcopy(CLASS_CAPABILITIES[unit['platform_class']]))
    for task in message['tasks']:
        params = task.setdefault('params', {})
        if task['task_type'] == 'T-ASL':
            for role in ('scout', 'assessor'):
                if isinstance(params.get(role), dict) and 'sensor' in params[role]:
                    params.setdefault('_source_physical_requirements', {})[role] = params[role].pop('sensor')
                    params[role].setdefault('capabilities', {'RCN': 2})
                if isinstance(params.get(role), dict) and params[role].get('unit'):
                    params[role + '_unit'] = params[role]['unit']
            params.setdefault('payload_required', 4.0)
    formation.setdefault('meta', {})['import_adapter'] = dict(
        matching_policy='current_capability_gates',
        physical_profiles='_source_profile',
        note='原始物理画像保留；任务分配沿用当前工程能力和载荷模型，不宣称物理参数匹配验收。')
    formation['meta']['motion_model'] = 'acceleration_limited'
    return message, formation


def source_geometry(formation):
    obstacles = [item for item in formation.get('constraints', [])
                 if item.get('type') == 'no_go']
    return dict(label='同源 SDF 六栋楼场景', buildings=obstacles,
                roadside_obstacles=[])
