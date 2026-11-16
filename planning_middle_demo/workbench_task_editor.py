"""Task types and parameter catalog accepted by the workbench editor.

The five 4.1 task templates are T-RCN/T-SEC/T-PTL/T-HLD/T-ASL. The catalog is
the single source of truth for the editor's per-parameter windows: the
front-end renders every parameter with its own input, and new tasks are seeded
from the type defaults so a task that has never existed can still be fully
configured and saved. Red-side target parameters (tracking/observation/relay
targets, intruders, the assault point) live in ``workbench_target_editor`` and
are intentionally absent from this catalog.
"""
from copy import deepcopy
import json
from pathlib import Path

from interop.model import TASK_TYPE_LABELS


# Each entry provides a valid starter geometry for the existing task template.
# The editor and both save paths share this registry.
EDITOR_TASK_GEOMETRY = {
    'T-RCN': {'target_list': [[0, 0]]},
    'T-SEC': {'defense_area': [[-2, -2], [2, -2], [2, 2], [-2, 2]]},
    'T-PTL': {'route': [[0, 0], [4, 0]]},
    'T-HLD': {'key_point': [0, 0]},
    # T-ASL 的目标是单个突击点；效果参数（effect/required_* 等）由
    # interop.message 校验并归一化，这里只给一个可编辑的起点。
    'T-ASL': {'point': [0, 0]},
}
EDITABLE_TYPES = frozenset(EDITOR_TASK_GEOMETRY)

TASK_TYPE_ORDER = ('T-RCN', 'T-SEC', 'T-PTL', 'T-HLD', 'T-ASL')
TASK_DEMO_FILES = dict(zip(TASK_TYPE_ORDER, ('crossroad_recon', 'area_containment',
                                          'area_patrol', 'key_point_hold', 'asl_junction')))

# Parameter windows per task type. ``kind`` selects the editor widget and
# ``template`` is the value inserted when the user enables an absent parameter
# (or the structural hint used by the generic object/list editors).
TASK_PARAM_CATALOG = {
    'T-RCN': [
        dict(key='duration_s', kind='number'),
        dict(key='search_deadline_s', kind='number'),
        dict(key='search_limit_s', kind='number', label='侦察限时（从下发计，秒）'),
        dict(key='cell', kind='number'),
        dict(key='coverage_target', kind='number'),
        dict(key='sensor_radius_m', kind='object', template={'ground': 9, 'air': 13},
             labels={'ground': '地面半径（米）', 'air': '空中半径（米）'}),
        dict(key='air_search_speed_mps', kind='number',
             label='空中侦察速度（米/秒，留空自动）'),
        dict(key='air_max_yaw_rate', kind='number',
             label='飞机最大转率（弧度/秒）'),
        dict(key='search_starts', kind='object', template={}, value_kind='point',
             hint='键为平台编号，值为侦察起点坐标；数量须与最少平台一致'),
        dict(key='search_points', kind='point_list', label='侦察起点',
             hint='每个起点对应一个侦察席位，平台由规划器分配'),
        dict(key='coordination', kind='string_list', template=[]),
        dict(key='after_event', kind='text'),
    ],
    'T-SEC': [
        dict(key='hold_duration_s', kind='number'),
        dict(key='target_start_mode', kind='text', template='after_control',
             options={'after_control': '封控建立后出场', 'task_clock': '从任务启动计时'},
             hint='红方目标的出场延时从所选事件开始计时。'),
        dict(key='roles', kind='object', template={'boundary': 2, 'gate': 1,
                                                   'intercept': 1, 'reserve': 0,
                                                   'air': 0},
             labels={'boundary': '边界段席位', 'gate': '门哨席位',
                     'intercept': '机动拦截席位', 'reserve': '预备队席位',
                     'air': '空中席位'}),
        dict(key='gates', kind='object_list', template=[], item={
            'gate_id': 'G1', 'point': [0, 0], 'width': 12, 'direction': [0, 1]}),
        dict(key='entry_points', kind='point_list', template=[]),
        dict(key='assembly_point', kind='point', template=[0, 0]),
        dict(key='assembly_radius_m', kind='number'),
        dict(key='control_objective', kind='text', options={'deny_entry': '禁止进入',
                                                           'control_passage': '管制通行',
                                                           'monitor_channel': '监视通道',
                                                           'intercept': '拦截'}),
        dict(key='control_level', kind='text', options={'monitor': '监视', 'warn': '警告', 'block': '拦阻'}),
        dict(key='engagement_authority', kind='text', options={'none': '无授权',
                                                              'self_defense': '仅自卫', 'on_order': '奉命'}),
        dict(key='max_leak_rate', kind='number'),
        dict(key='sensor_radius_m', kind='number'),
        dict(key='standoff_m', kind='number'),
        dict(key='warn_range_m', kind='number'),
        dict(key='warning_response_s', kind='number', template=2),
        dict(key='retreat_clearance_m', kind='number', template=10),
        dict(key='intercept_standoff_m', kind='number'),
        dict(key='intercept_post', kind='point', template=[0, 0]),
        dict(key='reserve_post', kind='point', template=[0, 0]),
        dict(key='rotation_s', kind='number'),
        dict(key='occupancy_tolerance_s', kind='number'),
        dict(key='boundary_sample_m', kind='number'),
        dict(key='air_unit', kind='text'),
        dict(key='air_altitude_m', kind='number'),
        dict(key='air_orbit_radius_m', kind='number'),
        dict(key='air_orbit_period_s', kind='number'),
        dict(key='air_speed_mps', kind='number'),
        dict(key='coordination', kind='string_list', template=[]),
        dict(key='after_event', kind='text'),
        dict(key='relay_verdict', kind='bool', template=False),
    ],
    'T-PTL': [
        dict(key='duration_s', kind='number'),
        dict(key='cycles', kind='number'),
        dict(key='follow_boundary', kind='bool', template=False),
        dict(key='checkpoints', kind='point_list', template=[]),
        dict(key='start_units', kind='string_list', template=[]),
        dict(key='handover_points', kind='point_list', template=[]),
        dict(key='sensor_radius_m', kind='object',
             labels={'ground': '地面探测半径（米）', 'air': '空中探测半径（米）'}),
        dict(key='coordination', kind='string_list', template=[]),
        dict(key='after_event', kind='text'),
    ],
    'T-HLD': [
        dict(key='hold_duration_s', kind='number'),
        dict(key='hold_criteria', kind='text', options={'quantity': '在位数量', 'coverage': '观察覆盖'}),
        dict(key='min_on_post', kind='number'),
        dict(key='min_key_point_coverage', kind='number'),
        dict(key='observation_ring_m', kind='number'),
        dict(key='observation_gap_max_s', kind='number'),
        dict(key='observation_samples', kind='number'),
        dict(key='sensor_radius_m', kind='number'),
        dict(key='post_radius_m', kind='number'),
        dict(key='post_tolerance_m', kind='number'),
        dict(key='reserve_standoff_m', kind='number'),
        dict(key='positions', kind='object_list', template=[], item={
            'id': 'P1', 'point': [0, 0], 'facing_deg': 0, 'min_units': 1}),
        dict(key='defense_positions', kind='point_list', template=[]),
        dict(key='threat_directions', kind='object_list', template=[], item={
            'id': 'N', 'bearing_deg': 0, 'width_deg': 60}),
        dict(key='roles', kind='object', template={'post': 4, 'reserve': 1,
                                                   'support': 0, 'relay': 0,
                                                   'air': 0},
             labels={'post': '阵位席位', 'reserve': '预备队席位',
                     'support': '支援席位', 'relay': '中继席位',
                     'air': '空中席位'}),
        dict(key='reserve_point', kind='point', template=[0, 0]),
        dict(key='support_points', kind='point_list', template=[]),
        dict(key='relay_point', kind='point', template=[0, 0]),
        dict(key='relief', kind='object', template={'interval_s': 50,
                                                    'handover_tol_m': 3,
                                                    'swap_requires_arrival': True,
                                                    'relief_cycles': 2}),
        dict(key='reinforce', kind='object', template={'trigger': 'position_lost',
                                                       'enemy_ratio': 1.5,
                                                       'arrive_within_s': 60}),
        dict(key='withdraw', kind='object', template={'allowed': False,
                                                      'route': [[0, 0], [0, 10]],
                                                      'deadline_s': 45},
             labels={'allowed': '先撤至集结点再返航'}),
        dict(key='counter_attack', kind='object', template={'authorized': True,
                                                            'max_range_m': 70,
                                                            'allowed_in_position': True}),
        dict(key='effect', kind='object', template={'kinds': ['damage', 'suppress'],
                                                    'adjudicator': 'stub',
                                                    'required_duration': 8}),
        dict(key='enemy_events', kind='object_list', template=[], item={
            't_s': 0, 'kind': 'probe', 'direction': 'N'}),
        dict(key='assembly_point', kind='point', template=[0, 0]),
        dict(key='patrol_enabled', kind='bool', template=False),
        dict(key='patrol_radius_m', kind='number'),
        dict(key='patrol_speed_mps', kind='number'),
        dict(key='patrol_period_s', kind='number'),
        dict(key='air_unit', kind='text'),
        dict(key='air_altitude_m', kind='number'),
        dict(key='air_orbit_radius_m', kind='number'),
        dict(key='air_orbit_period_s', kind='number'),
        dict(key='air_speed_mps', kind='number'),
        dict(key='coordination', kind='string_list', template=[]),
        dict(key='after_event', kind='text'),
        dict(key='relay_verdict', kind='bool', template=False),
    ],
    'T-ASL': [
        dict(key='duration_s', kind='number'),
        dict(key='effect', kind='text', options={'damage': '毁伤', 'suppress': '压制', 'seize': '夺占'}),
        dict(key='required_level', kind='number'),
        dict(key='required_duration', kind='number'),
        dict(key='required_control_s', kind='number'),
        dict(key='payload_required', kind='number'),
        dict(key='attack_window', kind='point', template=[0, 0],
             axes=('开始秒', '结束秒')),
        dict(key='scout', kind='object', template={
            'count': 1, 'capabilities': {'RCN': 2}, 'unit': None}),
        dict(key='assessor', kind='object', template={
            'count': 1, 'capabilities': {'RCN': 1}, 'unit': None}),
        dict(key='staging_center', kind='point', template=[0, 0]),
        dict(key='staging_radius', kind='number'),
        dict(key='assessment_post', kind='point', template=[0, 0]),
        dict(key='objective_radius', kind='number'),
        dict(key='observe_radius', kind='number'),
        dict(key='observe_angle', kind='number'),
        dict(key='sensor_radius_m', kind='number'),
        dict(key='arrive_tol', kind='number'),
        dict(key='sync_tol', kind='number'),
        dict(key='confirm_radius', kind='number'),
        dict(key='assessment_delay', kind='number'),
        dict(key='confirmation_deadline', kind='number'),
        dict(key='execute_deadline', kind='number'),
        dict(key='withdraw', kind='bool', template=False),
        dict(key='withdraw_point', kind='point', template=[0, 0]),
        dict(key='withdraw_ring', kind='number'),
        dict(key='withdraw_deadline', kind='number'),
        dict(key='roe', kind='text'),
        dict(key='collateral_limit', kind='text'),
        dict(key='positive_id_required', kind='bool', template=True),
        dict(key='waves', kind='number'),
        dict(key='ammo_per_platform', kind='number'),
        dict(key='result_items', kind='object_list', template=[], item={
            'id': '', 'required': True, 'criterion': ''}),
        dict(key='tail_timeout_s', kind='number'),
    ],
}

# New tasks are seeded from these values so they can be saved without the user
# filling every planner knob first. T-ASL keeps 3 units because the 4.1
# validator reserves one scout + one assessor seat before the assault seats.
TASK_DEFAULTS = {
    'T-RCN': dict(priority=3, min_units=1, max_units=1,
                  params={'duration_s': 120,
                          'sensor_required': {'type': 'eo', 'min_range_m': 1500.0},
                          'motion_required': {'min_speed_mps': 3.0}}),
    'T-SEC': dict(priority=3, min_units=1, max_units=1,
                  params={'hold_duration_s': 120,
                          'sensor_required': {'type': 'eo', 'min_range_m': 800.0},
                          'air_sensor_required': {'type': 'sar',
                                                  'min_range_m': 4000.0}}),
    'T-PTL': dict(priority=3, min_units=1, max_units=1,
                  params={'duration_s': 120,
                          'sensor_required': {'type': 'eo', 'min_range_m': 1000.0}}),
    'T-HLD': dict(priority=3, min_units=1, max_units=1,
                  params={'hold_duration_s': 120,
                          'sensor_required': {'type': 'eo', 'min_range_m': 1200.0},
                          'air_sensor_required': {'type': 'sar',
                                                  'min_range_m': 4000.0}}),
    'T-ASL': dict(priority=3, min_units=3, max_units=3,
                  params={'duration_s': 140,
                          'payload_required_kg': 400.0,
                          'sensor_required': {'type': 'any', 'min_range_m': 3000.0},
                          'scout': {'count': 1,
                                    'capabilities': {'RCN': 2},
                                    'unit': None},
                          'assessor': {'count': 1,
                                       'capabilities': {'RCN': 1},
                                       'unit': None}}),
}

# 载荷/传感器/续航/运动性能四类任务约束；所有任务类型共用。
_COMMON_REQUIREMENTS = [
    dict(key='payload_required_kg', kind='number'),
    dict(key='sensor_required', kind='object',
         template={'type': 'eo', 'min_range_m': 1000.0,
                   'max_resolution_m': 0.5}),
    dict(key='endurance_required_s', kind='number'),
    dict(key='motion_required', kind='object',
         template={'min_speed_mps': 0, 'min_accel_mps2': 0,
                   'min_yaw_rate_rad_s': 0, 'min_climb_rate_mps': 0,
                   'min_altitude_ceiling_m': 0, 'max_turn_radius_m': 0}),
]
for _entries in TASK_PARAM_CATALOG.values():
    _entries.extend(deepcopy(_COMMON_REQUIREMENTS))
for _task_type in ('T-SEC', 'T-HLD'):
    TASK_PARAM_CATALOG[_task_type].append(dict(
        key='air_sensor_required', kind='object',
        template={'type': 'sar', 'min_range_m': 4000.0,
                  'max_resolution_m': 1.0}))
TASK_PARAM_CATALOG['T-HLD'].append(dict(
    key='air_capabilities', kind='object', template={'RCN': 2}))

# Labels for every parameter key the editor can render, including nested item
# keys. Unknown keys fall back to the raw key name in the front-end.
PARAM_LABELS = {
    # 通用 / 侦察
    'duration_s': '作业时长（秒）',
    'hold_duration_s': '坚守时长（秒）',
    'search_deadline_s': '搜索截止（秒）',
    'cell': '网格尺寸（米）',
    'coverage_target': '覆盖率目标（0–1）',
    'sensor_radius_m': '探测半径（米）',
    'air_search_speed_mps': '空中侦察速度（米/秒）',
    'air_max_yaw_rate': '飞机最大转率（弧度/秒）',
    'search_starts': '侦察起点（按平台）',
    'coordination': '协同要求',
    'after_event': '事件后激活',
    'relay_verdict': '接力判定',
    # 封控
    'roles': '兵力编成',
    'gates': '通道口',
    'entry_points': '入口点',
    'assembly_point': '集结点',
    'assembly_radius_m': '集结半径（米）',
    'control_objective': '控制目标',
    'control_level': '控制等级',
    'engagement_authority': '交战授权',
    'max_leak_rate': '最大漏过率',
    'standoff_m': '站位内缩（米）',
    'warn_range_m': '警告距离（米）',
    'warning_response_s': '服从目标的警告响应时间（秒）',
    'retreat_clearance_m': '撤离至出场点外的距离（米）',
    'intercept_standoff_m': '拦截站位距离（米）',
    'intercept_post': '拦截待机点',
    'reserve_post': '预备队待机点',
    'rotation_s': '轮换周期（秒）',
    'occupancy_tolerance_s': '占位容差（秒）',
    'boundary_sample_m': '边界采样间距（米）',
    # 巡逻
    'cycles': '巡逻圈数',
    'follow_boundary': '沿边界巡逻',
    'checkpoints': '巡逻检查点',
    'start_units': '起巡平台',
    'handover_points': '交接点',
    # 坚守
    'hold_criteria': '坚守判定口径',
    'min_on_post': '最少在位',
    'min_key_point_coverage': '要点最小覆盖率',
    'observation_ring_m': '观察环半径（米）',
    'observation_gap_max_s': '最大观察中断（秒）',
    'observation_samples': '观察采样数',
    'post_radius_m': '阵位布设半径（米）',
    'post_tolerance_m': '阵位容差（米）',
    'reserve_standoff_m': '预备队距离（米）',
    'positions': '阵位',
    'defense_positions': '阵位（兼容字段）',
    'threat_directions': '威胁方向',
    'reserve_point': '预备队待机点',
    'support_points': '支援点',
    'relay_point': '中继点',
    'relief': '轮换规则',
    'reinforce': '增援规则',
    'withdraw': '撤离规则',
    'counter_attack': '反击规则',
    'effect': '效果判定',
    'enemy_events': '敌方事件',
    'patrol_enabled': '启用阵内巡逻',
    'patrol_radius_m': '巡逻半径（米）',
    'patrol_speed_mps': '巡逻速度（米/秒）',
    'patrol_period_s': '巡逻周期（秒）',
    # 空中席位（多类任务共用）
    'air_unit': '空中平台编号',
    'air_capabilities': '空中能力门槛',
    'air_altitude_m': '空中高度（米）',
    'air_orbit_radius_m': '空中盘旋半径（米）',
    'air_orbit_period_s': '空中盘旋周期（秒）',
    'air_speed_mps': '空中速度（米/秒）',
    # 突击
    'required_level': '规定毁伤等级',
    'required_duration': '规定压制时长（秒）',
    'required_control_s': '规定控制时长（秒）',
    'payload_required': '所需载荷',
    'attack_window': '攻击时间窗',
    'scout': '侦察席位',
    'assessor': '评估席位',
    'staging_center': '集结中心',
    'staging_radius': '集结半径（米）',
    'assessment_post': '评估站位',
    'objective_radius': '目标半径（米）',
    'observe_radius': '观察半径（米）',
    'observe_angle': '观察扇区角（弧度）',
    'arrive_tol': '到位容差（米）',
    'sync_tol': '同步容差（秒）',
    'confirm_radius': '确认半径（米）',
    'assessment_delay': '评估延迟（秒）',
    'confirmation_deadline': '确认时限（秒）',
    'execute_deadline': '执行时限（秒）',
    'withdraw_point': '撤离点',
    'withdraw_ring': '撤离环半径（米）',
    'withdraw_deadline': '撤离时限（秒）',
    'roe': '交战规则',
    'collateral_limit': '附带损伤限制',
    'positive_id_required': '需目视识别',
    'waves': '打击波次',
    'ammo_per_platform': '单台弹药',
    'result_items': '结果判定项',
    'tail_timeout_s': '收尾超时（秒）',
    # 嵌套键
    'target_id': '目标编号',
    'object_label': '目标名称',
    'start': '起点坐标',
    'goal': '终点坐标',
    'point': '点位坐标',
    'speed_mps': '移动速度（米/秒）',
    'move_after_s': '出现时刻（秒）',
    'track_outside_s': '区外跟踪时长（秒）',
    'track_until_stop': '持续跟踪至目标停止',
    'move_after_contact': '跟踪平台接触后再移动',
    'stop_orbit_s': '目标停止后空中盘旋时长（秒）',
    't_start_s': '出场延时或时刻（秒）',
    'target_start_mode': '目标出场方式',
    'authorized': '已授权',
    'compliance': '服从检查',
    'ground': '地面半径（米）',
    'air': '空中半径（米）',
    'boundary': '边界段席位',
    'gate': '门哨席位',
    'intercept': '机动拦截席位',
    'reserve': '预备队席位',
    'post': '阵位席位',
    'support': '支援席位',
    'relay': '中继席位',
    'gate_id': '通道编号',
    'width': '宽度（米）',
    'direction': '方向向量',
    'id': '编号',
    'facing_deg': '朝向（度）',
    'min_units': '最少平台',
    'bearing_deg': '方位角（度）',
    'width_deg': '扇区宽度（度）',
    't_s': '时刻（秒）',
    'kind': '类型',
    'ratio': '兵力比',
    'count': '席位数量',
    'capabilities': '能力要求',
    'unit': '指定平台编号',
    'interval_s': '轮换间隔（秒）',
    'handover_tol_m': '交接容差（米）',
    'swap_requires_arrival': '需到位交接',
    'relief_cycles': '轮换次数',
    'trigger': '触发条件',
    'enemy_ratio': '敌方兵力比',
    'arrive_within_s': '到位时限（秒）',
    'allowed': '允许撤离',
    'route': '路线',
    'deadline_s': '时限（秒）',
    'kinds': '效果种类',
    'adjudicator': '判定器',
    'max_range_m': '最大距离（米）',
    'allowed_in_position': '允许在位反击',
    'required': '必需',
    'criterion': '判据',
    # 明确单位的任务约束
    'payload_required_kg': '载荷要求（千克）',
    'sensor_required': '传感器要求',
    'air_sensor_required': '空中传感器要求',
    'endurance_required_s': '续航要求（秒）',
    'motion_required': '运动性能要求',
    'type': '类型 / 类别',
    'min_range_m': '最小探测距离（米）',
    'max_resolution_m': '最大分辨率（米）',
    'min_fov_deg': '最小视场（度）',
    'range_m': '探测距离（米）',
    'fov_deg': '视场（度）',
    'resolution_m': '分辨率（米）',
    'min_speed_mps': '最小速度（米/秒）',
    'min_accel_mps2': '最小加速度（米/秒²）',
    'min_yaw_rate_rad_s': '最小角速度（弧度/秒）',
    'min_climb_rate_mps': '最小爬升率（米/秒）',
    'min_altitude_ceiling_m': '最低升限（米）',
    'max_turn_radius_m': '最大转弯半径（米）',
    'max_speed_mps': '最大速度（米/秒）',
    'max_accel_mps2': '最大加速度（米/秒²）',
    'max_yaw_rate_rad_s': '最大角速度（弧度/秒）',
    'max_climb_rate_mps': '最大爬升率（米/秒）',
    'max_altitude_m': '最大高度（米）',
    'RCN': '侦察能力',
    'STK': '打击能力',
    'PTL': '巡逻能力',
    'HLD': '坚守能力',
}


def _catalog_entry(spec):
    entry = dict(spec)
    kind = entry['kind']
    if 'template' in entry:
        entry['template'] = deepcopy(entry['template'])
    elif kind == 'point':
        entry['template'] = [0, 0]
    elif kind == 'number':
        entry['template'] = 0
    elif kind == 'bool':
        entry['template'] = False
    elif kind == 'text':
        entry['template'] = ''
    elif kind in ('point_list', 'string_list', 'object_list'):
        entry['template'] = []
    else:
        entry['template'] = {}
    if 'item' in entry:
        entry['item'] = deepcopy(entry['item'])
    entry.setdefault('label', PARAM_LABELS.get(entry['key'], entry['key']))
    return entry


def editor_task_types():
    from workbench_target_editor import editor_targets

    types = {}
    for key in TASK_TYPE_ORDER:
        path = Path(__file__).parent / 'interop' / 'scenarios' / (TASK_DEMO_FILES[key] + '.message.json')
        demo = json.loads(path.read_text(encoding='utf-8-sig'))['tasks'][0]
        demo.pop('description', None)
        params = demo['params']
        for pin in ('start_units', 'air_unit', 'scout_unit', 'assessor_unit'):
            params.pop(pin, None)
        for role in ('scout', 'assessor'):
            if role in params:
                params[role].pop('unit', None)
        if key == 'T-RCN':
            params['search_points'] = list(params.pop('search_starts').values())
            params['search_limit_s'] = params.pop('search_deadline_s') - demo['window']['start_s']
            if params.get('tracking_target'):
                params['tracking_target'].update(track_until_stop=True, move_after_contact=True)
        elif key == 'T-SEC':
            params['target_start_mode'] = 'after_control'
        types[key] = {
            'label': TASK_TYPE_LABELS[key],
            'target': deepcopy(EDITOR_TASK_GEOMETRY[key]),
            'params': [_catalog_entry(spec) for spec in TASK_PARAM_CATALOG[key]],
            'defaults': deepcopy(TASK_DEFAULTS[key]),
            'demo': demo,
            'demo_targets': editor_targets({'tasks': [demo]}),
        }
    return types


def editor_param_labels():
    return dict(PARAM_LABELS)


def is_editable_task(task):
    if not isinstance(task, dict) or task.get('task_type') not in EDITABLE_TYPES:
        return False
    return True
