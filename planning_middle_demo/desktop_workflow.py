"""Native desktop configuration adapters; reuse existing contracts and worker.

No planner or simulation algorithms live here. Edits create new input snapshots.
"""
import json


def editor_metadata(message):
    """Return the task-form and red-target catalogs for one 4.1 message.

    The catalogs are display metadata only. Existing task fields, target
    parameters and unknown extension fields remain in the 4.1 message and are
    never replaced by defaults merely because the editor is opened.
    """
    from workbench_task_editor import editor_task_types
    from workbench_target_editor import (editor_target_slots,
                                         editor_targets)

    tasks = message.get('tasks') if isinstance(message, dict) else None
    return dict(
        task_types=editor_task_types(),
        target_slots=editor_target_slots(),
        targets=editor_targets(message),
        task_count=len(tasks) if isinstance(tasks, list) else 0,
    )


def apply_editor_targets(message, targets):
    """Apply the dedicated target panel to a 4.1 message copy."""
    from workbench_target_editor import apply_targets

    if not isinstance(message, dict):
        raise ValueError('任务消息必须是 JSON 对象')
    edited = dict(message)
    edited['tasks'] = apply_targets(message.get('tasks'), targets)
    return dict(message=edited, editor=editor_metadata(edited))


def preview_task(payload):
    """Preview one task draft on the current map without starting a run.

    The native task form uses this endpoint to recommend a map position, show
    which platform would take each seat, and apply the same geometry movement
    semantics as the final editor save.
    """
    from workbench_patrol_editor import preview_task as run_preview

    if not isinstance(payload, dict):
        raise ValueError('任务试算参数必须是 JSON 对象')
    allowed = {'message', 'formation', 'task_id', 'targets', 'recommend',
               'center', 'now', 'occupied', 'completed', 'objective',
               'max_ticks'}
    if set(payload) - allowed:
        raise ValueError('任务试算包含不支持的参数')
    if not isinstance(payload.get('message'), dict):
        raise ValueError('任务试算缺少任务消息')
    if not isinstance(payload.get('formation'), dict):
        raise ValueError('任务试算缺少编成表')
    data = dict(payload)
    if 'targets' in data:
        message = dict(data['message'])
        message['tasks'] = apply_editor_targets(
            data['message'], data.get('targets') or [])['message']['tasks']
        data['message'] = message
        data.pop('targets', None)
    return run_preview(data)


def _initial_threat_overlap(scenario):
    """Count platforms whose initial pose falls inside applicable threats.

    This is a non-blocking warning: threat zones are soft risk areas. A
    platform starting inside one must still receive a finite route and move
    out step by step rather than being rejected as though it were inside a
    building.
    """
    from interop.geometry import point_in_polygon

    rows = []
    total_ground = total_air = 0
    for item in scenario.constraints:
        if item.get("type") != "threat":
            continue
        area = item.get("area") or {}
        polygon = area.get("polygon") if isinstance(area, dict) else area
        if not polygon or len(polygon) < 3:
            continue
        applies = str(item.get("applies_to", "ground"))
        covered = [
            platform for platform in scenario.platforms
            if ((applies in ("air", "all") and platform.is_air)
                or (applies in ("ground", "all") and not platform.is_air))
            and point_in_polygon(platform.position, polygon)
        ]
        ground = sum(1 for platform in covered if not platform.is_air)
        air = len(covered) - ground
        total_ground += ground
        total_air += air
        if covered:
            rows.append(dict(
                constraint_id=item.get("constraint_id"),
                applies_to=applies,
                ground=ground,
                air=air,
                unit_ids=[platform.unit_id for platform in covered],
            ))
    warning = ''
    if total_ground or total_air:
        warning = (
            "配置允许运行：威胁区覆盖了初始设备"
            "（对地 %d 台、对空 %d 台）。初始暴露会计入运行统计，"
            "执行将从当前位置逐步规划离开威胁区。"
            % (total_ground, total_air))
    return dict(
        allowed=True,
        total=total_ground + total_air,
        ground=total_ground,
        air=total_air,
        threats=rows,
        warning=warning,
    )


def validate_draft(backend, payload, *, materialize_inputs=True):
    if not isinstance(payload, dict) or set(payload) - {
            'request', 'message', 'formation', 'targets'}:
        raise ValueError('配置只能包含 request、message、formation 和 targets')
    request = backend.validate_config(payload.get('request'))
    message, formation = payload.get('message'), payload.get('formation')
    if request['scenario'] in backend.INTEROP_SCENARIOS:
        from interop.message import parse_message
        if not isinstance(message, dict) or not isinstance(formation, dict):
            raise ValueError('融合场景需要 4.1 任务消息和编成表 JSON 对象')
        from interop.urban_maps import apply_map_to_formation, _map_items
        if request['map_id'] == 'source':
            from workbench_cases import source_geometry
            map_geometry = source_geometry(formation)
        elif materialize_inputs:
            formation, map_geometry = apply_map_to_formation(
                formation, request['map_id'])
        else:
            # Saved inputs are evidence. New placement rules must never
            # regenerate old geometry when merely inspecting a record.
            map_geometry = _map_items(request['map_id'])
        placement = (message.get('_meta') or {}).get('task_placement')
        if materialize_inputs and request['randomize_tasks']:
            from interop.random_tasks import randomize_message, randomize_threats
            positions = [unit.get('position') for unit in formation['formation']['units']]
            positions = [(p['x'], p['y']) if isinstance(p, dict) else p for p in positions if p]
            start_point = tuple(sum(p[i] for p in positions)/len(positions) for i in (0,1)) if positions else None
            message, placement = randomize_message(
                message, request['map_id'], request['task_seed'],
                request['scenario'], start_point=start_point)
            formation = randomize_threats(formation, message, request['map_id'],
                                         request['task_seed'], start_point=start_point)
            formation.setdefault('meta', {})['task_randomization'] = placement
        if 'targets' in payload:
            from workbench_target_editor import apply_targets
            message = dict(message)
            message['tasks'] = apply_targets(message.get('tasks'),
                                             payload.get('targets'))
        scenario = parse_message(message, formation)
        if materialize_inputs and request['map_id'] != 'source':
            from interop.random_tasks import validate_task_bounds
            validate_task_bounds(message, request['map_id'])
        summary = dict(
            tasks=len(scenario.tasks),
            platforms=len(scenario.platforms),
            initial_threat_overlap=_initial_threat_overlap(scenario),
            map=dict(
                id=request['map_id'],
                label=map_geometry.get('label') or request['map_id'],
                buildings=len(map_geometry.get('buildings') or []),
                roadside_obstacles=len(
                    map_geometry.get('roadside_obstacles') or []),
            ),
            task_randomization=dict(
                enabled=request['randomize_tasks'],
                seed=request['task_seed'],
                placement=placement,
                reseed_on_run=request['reseed_on_run'],
            ),
        )
    else:
        if message is not None or formation is not None:
            raise ValueError('历史基座场景仅支持运行参数，不接受 4.1 输入覆盖')
        summary = dict(tasks=None, platforms=None)
    # Deep copy and reject NaN/Infinity before any run directory is created.
    draft = json.loads(json.dumps(dict(request=request, message=message,
                                      formation=formation), allow_nan=False))
    return draft, summary


def get_config(backend, scenario='interop_containment', run_id=None):
    source = 'template'
    request = {'scenario': scenario,
               'planner': 'interop' if scenario in backend.INTEROP_SCENARIOS else 'base'}
    message = formation = None
    if run_id:
        directory = backend.run_path(run_id)
        if not directory.is_dir():
            raise FileNotFoundError('运行不存在')
        manifest = backend.read_json(directory / 'manifest.json')
        request = manifest.get('workbench_config') or request
        if 'randomize_tasks' not in request:
            request = dict(request, randomize_tasks=False,
                           reseed_on_run=False)
        source = 'run_snapshot'
        native = directory / 'desktop_input.json'
        if native.is_file():
            saved = backend.read_json(native)
            message, formation = saved['message'], saved['formation']
        elif (directory / 'scenario.json').is_file():
            meta = (backend.read_json(directory / 'scenario.json').get('_meta') or {}).get('interop') or {}
            message, formation = meta.get('message'), meta.get('formation')
        scenario = request.get('scenario', scenario)
    request = backend.validate_config(request)
    if scenario in backend.INTEROP_SCENARIOS and (message is None or formation is None):
        if run_id:
            source = 'template_fallback'
        message, formation = backend.interop_inputs_for(scenario)
    draft, summary = validate_draft(
        backend, dict(request=request, message=message, formation=formation),
        materialize_inputs=source != 'run_snapshot')
    return dict(draft=draft, summary=summary, input_source=source,
                editable=scenario in backend.INTEROP_SCENARIOS,
                editor=editor_metadata(message) if message is not None else None,
                note='保存后创建新运行，原始记录和模板不变；不从回放时刻续算。')


def run_details(backend, run_id):
    doc = backend.load_run(run_id)
    return dict(id=run_id, report=doc.get('report') or {},
                manifest=doc.get('manifest') or {},
                files=doc.get('files') or [],
                plan=doc.get('plan'),
                agent_tasks=doc.get('agent_tasks'),
                agent_tasks_text=doc.get('agent_tasks_text'),
                chain_summary=doc.get('chain_summary'),
                execution_plan=doc.get('execution_plan'),
                reference_plan=doc.get('reference_plan'),
                note='计划、执行反馈和本地模拟结果需分别解读。')


def find_demo(backend, scenario):
    template = get_config(backend, scenario)['draft']
    candidates = sorted(backend.OUTPUTS.glob('*/manifest.json'), reverse=True)
    for path in candidates:
        try:
            manifest = backend.read_json(path)
            request = manifest.get('workbench_config') or {}
            if request.get('scenario') != scenario or request.get('mode') != 'normal':
                continue
            if not (path.parent / 'report.json').is_file():
                continue
            saved = get_config(backend, scenario, path.parent.name)
            if saved['input_source'] != 'run_snapshot':
                continue
            if all(saved['draft'][key] == template[key] for key in ('request', 'message', 'formation')):
                return dict(id=path.parent.name)
        except (OSError, ValueError, KeyError):
            continue
    return dict(id=None)


def refresh_legacy_preset(backend, payload):
    import hashlib
    task_randomized = False
    if isinstance(payload, dict) and isinstance(payload.get('request'), dict):
        raw_request = payload['request']
        if raw_request.get('randomize_tasks') and raw_request.get(
                'reseed_on_run', True):
            from interop.random_tasks import new_task_seed
            payload = dict(payload)
            payload['request'] = dict(
                raw_request, task_seed=new_task_seed())
            task_randomized = True
    draft, _ = validate_draft(backend, payload)
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                         separators=(',', ':')).encode()).hexdigest()
    legacy = (draft['request']['scenario'] == 'interop_recon'
              and digest(payload.get('message')) == 'ca164c11b6b7a57d7accc1d1a9bd4e1f710520d62d349f9783b661608c312402'
              and digest(payload.get('formation')) == '7cc0d26d8f75f5a8a4cf3f7d5d04825b941ef5c387aa4bb044426ef43bd1c11e')
    if legacy:
        current = get_config(backend, 'interop_recon')['draft']
        draft['message'], draft['formation'] = current['message'], current['formation']
    notes = []
    if legacy:
        notes.append('已将旧版默认侦察预设更新到建筑群；保留本轮规划目标和运行参数。')
    if task_randomized:
        notes.append('已为本次运行生成新的任务落点随机种子。')
    return dict(draft=draft, refreshed=legacy,
                task_randomized=task_randomized, note=' '.join(notes))


def storage_info(backend):
    return dict(directory=str(backend.OUTPUTS.resolve()),
                deleted_directory=str((backend.OUTPUTS / '.deleted').resolve()))


def move_record(backend, app, payload, restore=False):
    import uuid
    if not isinstance(payload, dict):
        raise ValueError('记录操作参数必须是 JSON 对象')
    with app.lock:
        root = backend.OUTPUTS.resolve()
        trash = root / '.deleted'
        if trash.resolve().parent != root:
            raise ValueError('已删除目录不能位于存储根目录之外')
        if restore:
            token = payload.get('token', '')
            if not isinstance(token, str) or not backend.re.fullmatch(r'[A-Za-z0-9_-]+', token):
                raise ValueError('无效恢复编号')
            source = trash / token
            if not source.is_dir() or source.resolve().parent != trash.resolve():
                raise ValueError('已删除记录不存在')
            run_id = token.rsplit('--', 1)[0]
            target = root / run_id
            if target.exists():
                raise ValueError('原位置已有同名记录，不能覆盖')
        else:
            run_id = payload.get('id', '')
            source = backend.run_path(run_id)
            if source.resolve().parent != root:
                raise ValueError('不能删除运行目录以外的路径')
            if app.process is not None and app.process.poll() is None and app.current == run_id:
                raise RuntimeError('该记录正在运行，不能删除')
            trash.mkdir(exist_ok=True)
            token = run_id + '--' + uuid.uuid4().hex
            target = trash / token
        source.rename(target)
        return dict(id=run_id, token=token, directory=str(target))
