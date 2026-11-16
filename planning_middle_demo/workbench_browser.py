"""Template/initial-input adapters; live and replay edits use the session API."""
from copy import deepcopy


def templates(backend):
    from workbench_task_editor import is_editable_task
    result = {}
    for key, label in backend.ALL_SCENARIOS.items():
        message, _ = backend.interop_inputs_for(key)
        request = backend.validate_config({'scenario': key, 'planner': 'interop'})
        result[key] = dict(label=label, max_ticks=request['max_ticks'],
                           editable=all(is_editable_task(t) for t in message['tasks']),
                           avoid=True, live=False)
    return result


def configuration(backend, preset, run_id=None, map_id=None):
    from desktop_workflow import get_config, validate_draft
    from workbench_task_editor import editor_param_labels
    from workbench_target_editor import editor_target_slots, editor_targets
    if run_id:
        draft = get_config(backend, preset, run_id)['draft']
        preset = draft['request']['scenario']
    else:
        message, formation = backend.interop_inputs_for(preset)
        request = dict(scenario=preset, planner='interop', randomize_tasks=True, task_seed=1)
        if map_id:
            request['map_id'] = map_id
        draft, _ = validate_draft(backend, dict(request=request, message=message,
                                                formation=formation))
    message, formation = draft['message'], draft['formation']
    from desktop_workflow import editor_metadata
    return dict(message=message, formation=formation, preset=preset,
                run_id=run_id, completed=[], sim_s=0, objective=draft['request']['objective'],
                request=draft['request'], max_ticks=draft['request']['max_ticks'],
                task_types=editor_metadata(message)['task_types'],
                targets=editor_targets(message), target_slots=editor_target_slots(),
                param_labels=editor_param_labels(), editable=True,
                edit_mode='new_run', note='保存为新的完整运行，从初始状态计算。')


def edited_draft(backend, edit, request):
    from desktop_workflow import validate_draft
    from interop.templates import decompose
    from interop.message import parse_message
    from workbench_patrol_editor import check_task_drafts
    from interop.runtime import OBJECTIVE_MAP
    if not isinstance(edit, dict) or set(edit) - {'source_run', 'tasks', 'units', 'targets', 'threats'}:
        raise ValueError('仅支持初始配置编辑；不支持暂停续算参数')
    if not {'tasks', 'units'} <= set(edit):
        raise ValueError('配置缺少任务或平台')
    base = configuration(backend, request['scenario'], edit.get('source_run'), request['map_id'])
    message, formation = deepcopy(base['message']), deepcopy(base['formation'])
    message['tasks'] = deepcopy(edit['tasks'])
    formation['formation']['units'] = deepcopy(edit['units'])
    if 'threats' in edit:
        threats = deepcopy(edit['threats'])
        if not isinstance(threats, list) or len(threats) > 30 or any(
                not isinstance(zone, dict) or zone.get('type') != 'threat' for zone in threats):
            raise ValueError('威胁区最多 30 个，且只允许 threat 类型')
        fixed = [zone for zone in formation.get('constraints', []) if zone.get('type') != 'threat']
        ids = [zone.get('constraint_id') for zone in fixed + threats]
        if any(not isinstance(ident, str) or not ident.strip() for ident in ids) or len(ids) != len(set(ids)):
            raise ValueError('威胁区编号不能为空或与现有约束重复')
        formation['constraints'] = fixed + threats
    # User-edited geometry is authoritative; never randomize it again at save.
    request = dict(request, randomize_tasks=False, reseed_on_run=False)
    payload = dict(request=request, message=message, formation=formation)
    if 'targets' in edit:
        payload['targets'] = edit['targets']
    draft, _ = validate_draft(backend, payload)
    scenario = parse_message(draft['message'], draft['formation'])
    decompose(scenario)
    check_task_drafts(scenario, objective=OBJECTIVE_MAP.get(request['objective'], 'timeliness'))
    return draft
