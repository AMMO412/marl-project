# -*- coding: utf-8 -*-
"""sdf_state.py —— 从甲方 SDF 场景提取"任务规划初始状态"。

回答一个具体问题：**规划开始时，场上有什么、在哪里、多大**。输入是
`资料/接口说明/container_00_combined_scene.sdf`（50 台平台 + 静态场景），
输出是一份可被场景/回放/工作台共同读取的 JSON：

  * robots     50 台平台：编号、类别（UGV/TANK/PLANE/WING）、初始位姿、
               底盘尺寸、含轮/起落架的外包络尺寸与包络半径、轮半径/轮距、
               控制插件、是否可爬升、初始高度。
  * obstacles  静态障碍（内联盒体 + 本地 model.sdf 的盒体/DAE 包围盒），
               坐标与 SDF 一致（米，未缩放）。
  * roads      道路/广场（`env_road_*`、`env_city_road_*`、`env_city_square`），
               画底图用，不是障碍。
  * landmarks  地标与区域引用（House/Office/baylands/yosemite/beacon），
               只有位姿，没有外部模型几何时**不臆造占地**。

口径与边界：
  * 尺寸是 SDF 碰撞几何的**外包络**，不是厂商实测外形；网格模型只登记
    引用，不从 DAE 猜尺寸（House/Office 的占地由 city_nav.mesh_aabb 读取
    本地 DAE 包围盒，来源字段会写明 `mesh_aabb`）。
  * 坐标系为 SDF 世界坐标（米）。规划场景若做缩放/平移，由场景 `_meta`
    负责换算，本文件不改坐标。
  * 只读 SDF；不连接 Gazebo，不代表仿真已被执行。

用法：
  py -3.14 planning_middle_demo/sdf_state.py            # 打印摘要
  py -3.14 planning_middle_demo/sdf_state.py --out planning_middle_demo/scenarios/sdf_initial_state.json
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
DEFAULT_SDF = PROJECT_ROOT / '资料' / '接口说明' / 'container_00_combined_scene.sdf'
DEFAULT_MODELS = PROJECT_ROOT / '资料' / '接口说明' / 'models'
DEFAULT_OUT = ROOT / 'scenarios' / 'sdf_initial_state.json'

# 号段 → 类别（与 fleet.py 一致；这里不 import fleet，保持本文件可独立运行）
KIND_RANGES = (('UGV', 1, 20), ('TANK', 21, 30), ('PLANE', 31, 40), ('WING', 41, 50))
KIND_LABEL = {'UGV': '轮式无人车', 'TANK': '履带无人车',
              'PLANE': '固定翼无人机', 'WING': '飞翼无人机'}
CLIMB_KINDS = {'PLANE', 'WING'}
ROAD_PREFIXES = ('env_road_', 'env_city_road_', 'env_city_square')
LANDMARK_PREFIXES = ('env_city_house', 'env_city_office', 'env_wetlands',
                     'env_yosemite', 'env_beacon')


def kind_of(no):
    for kind, lo, hi in KIND_RANGES:
        if lo <= no <= hi:
            return kind
    raise ValueError('机器人编号超出 1-50：%r' % no)


def _pose(node, default='0 0 0 0 0 0'):
    values = [float(v) for v in (node.findtext('pose') or default).split()]
    if len(values) != 6:
        raise ValueError('位姿应为六元组：%r' % values)
    return values


def _rotate_xy(x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return c * x - s * y, s * x + c * y


def _combine(a, b):
    """平面刚体变换复合（与 city_nav._combine 同口径）。"""
    x, y = _rotate_xy(b[0], b[1], a[5])
    return [a[0] + x, a[1] + y, a[2] + b[2], 0.0, 0.0, a[5] + b[5]]


def _link_pose(model, link):
    return _combine(_pose(model), _pose(link)) if link.find('pose') is not None \
        else _combine(_pose(model), [0, 0, 0, 0, 0, 0])


def _shape_box(geometry, transform):
    """几何体在模型坐标系下的轴对齐包围盒 [x0,y0,z0,x1,y1,z1]。"""
    box = geometry.find('box')
    if box is not None:
        size = [float(v) for v in (box.findtext('size') or '').split()]
        if len(size) != 3:
            return None
        lx, ly, lz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
        corners = [(sx * lx, sy * ly, sz * lz)
                   for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        xs, ys, zs = [], [], []
        for cx, cy, cz in corners:
            rx, ry = _rotate_xy(cx, cy, transform[5])
            xs.append(transform[0] + rx)
            ys.append(transform[1] + ry)
            zs.append(transform[2] + cz)
        return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
    sphere = geometry.find('sphere')
    if sphere is not None:
        radius = float(sphere.findtext('radius') or 0.0)
        return [transform[0] - radius, transform[1] - radius, transform[2] - radius,
                transform[0] + radius, transform[1] + radius, transform[2] + radius]
    cylinder = geometry.find('cylinder')
    if cylinder is not None:
        radius = float(cylinder.findtext('radius') or 0.0)
        length = float(cylinder.findtext('length') or 0.0)
        return [transform[0] - radius, transform[1] - radius, transform[2] - length / 2,
                transform[0] + radius, transform[1] + radius, transform[2] + length / 2]
    return None


def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), min(b[2] for b in boxes),
            max(b[3] for b in boxes), max(b[4] for b in boxes), max(b[5] for b in boxes)]


def _size(box):
    return [round(box[3] - box[0], 3), round(box[4] - box[1], 3),
            round(box[5] - box[2], 3)]


def read_robots(world):
    robots = []
    for model in world.findall('model'):
        if model.findtext('static') == 'true':
            continue
        name = model.get('name') or ''
        if not name.startswith('robot_'):
            continue
        no = int(name.split('_')[-1])
        kind = kind_of(no)
        pose = _pose(model)
        boxes, meshes = [], []
        wheel_radius = wheel_separation = None
        chassis_box = None
        left = right = None
        for link in model.findall('link'):
            transform = _link_pose(model, link)
            lname = link.get('name')
            for collision in link.findall('collision'):
                geometry = collision.find('geometry')
                if geometry is None:
                    continue
                local = _combine(transform, _pose(collision)) \
                    if collision.find('pose') is not None else transform
                box = _shape_box(geometry, local)
                if box:
                    boxes.append(box)
                    if lname == 'chassis' and geometry.find('box') is not None:
                        chassis_box = _shape_box(geometry, local)
                mesh = geometry.find('mesh')
                if mesh is not None:
                    uri = (mesh.findtext('uri') or '').split('/')[-1]
                    if uri and uri not in meshes:
                        meshes.append(uri)
                sphere = geometry.find('sphere')
                if sphere is not None and lname and 'wheel' in lname:
                    wheel_radius = float(sphere.findtext('radius') or 0.0)
            if lname == 'left_wheel':
                left = _pose(link)
            elif lname == 'right_wheel':
                right = _pose(link)
        if left is not None and right is not None:
            wheel_separation = round(abs(left[1] - right[1]), 3)
        envelope = _union(boxes)
        plugins = [p.get('filename') or '' for p in model.findall('plugin')]
        control = next((p.split('/')[-1] for p in plugins
                        if 'diff-drive' in p or 'velocity-control' in p), None)
        can_climb = kind in CLIMB_KINDS
        robots.append(dict(
            no=no, name=name, kind=kind, kind_label=KIND_LABEL[kind],
            pose=[round(v, 4) for v in pose],
            start=[round(pose[0], 3), round(pose[1], 3)],
            start_z=round(pose[2], 3),
            can_climb=can_climb,
            control_plugin=control,
            mesh=meshes[0] if meshes else None,
            chassis_size=(_size(chassis_box) if chassis_box else None),
            envelope_size=(_size(envelope) if envelope else None),
            envelope_radius=(round(math.hypot(
                (envelope[3] - envelope[0]) / 2.0,
                (envelope[4] - envelope[1]) / 2.0), 3) if envelope else None),
            wheel_radius=wheel_radius,
            wheel_separation=wheel_separation,
            collision_count=len(boxes),
        ))
    robots.sort(key=lambda r: r['no'])
    return robots


def _rect(box, yaw=0.0):
    """轴对齐盒体 → 平面矩形多边形（SDF 内联盒体均无 roll/pitch）。"""
    width, height = box[0], box[1]
    corners = [(-width / 2, -height / 2), (width / 2, -height / 2),
               (width / 2, height / 2), (-width / 2, height / 2)]
    out = []
    for cx, cy in corners:
        x, y = _rotate_xy(cx, cy, yaw)
        out.append([round(box[3] + x, 3), round(box[4] + y, 3)])
    return out


def read_statics(world, models_dir, sdf=None):
    """静态几何：障碍复用 city_nav 的成熟解析，道路/广场单独登记为底图。

    障碍解析必须和规划用的 NavMap 同源，否则"图上画的障碍"和"规划器
    真正躲的障碍"会不一致。这里直接调用 city_nav.load_sdf_obstacles：
    它只接受显式盒体 / 本地 DAE 包围盒，网格缺失的模型记入 missing。
    道路与广场（`env_road_*`、`env_city_road_*`、`env_city_square`）在
    规划中是通行面，单独返回给回放当底图，不参与避障。
    """
    from city_nav import load_sdf_obstacles
    loaded = load_sdf_obstacles(sdf, bounds=None,
                                models_dir=Path(models_dir) if models_dir else None)
    obstacles = [dict(id=o['id'], label=o.get('label') or o['id'],
                      source=o.get('footprint', 'box'),
                      size=o.get('size_m'),
                      polygon=[[round(x, 3), round(y, 3)] for x, y in o['polygon']])
                 for o in loaded['obstacles']]
    roads = []
    for model in world.findall('model'):
        if model.findtext('static') != 'true':
            continue
        name = model.get('name') or ''
        if not name.startswith(ROAD_PREFIXES):
            continue
        pose = _pose(model)
        for link in model.findall('link'):
            transform = _combine(pose, _pose(link)) if link.find('pose') is not None else pose
            for collision in link.findall('collision'):
                box = collision.find('geometry/box')
                if box is None:
                    continue
                size = [float(v) for v in (box.findtext('size') or '').split()]
                local = _combine(transform, _pose(collision)) \
                    if collision.find('pose') is not None else transform
                roads.append(dict(id=name, size=size,
                                  pose=[round(v, 4) for v in local],
                                  polygon=_rect([size[0], size[1], size[2],
                                                 local[0], local[1]], local[5])))
    missing = [dict(name=m.get('model') or m.get('name'),
                    uri=m.get('uri'), reason=m.get('reason'))
               for m in loaded['missing']]
    return obstacles, roads, missing


def read_landmarks(world):
    rows = []
    for model in world.findall('model'):
        name = model.get('name') or ''
        if name.startswith(LANDMARK_PREFIXES):
            rows.append(dict(name=name, kind='beacon', pose=[round(v, 3) for v in _pose(model)]))
    for include in world.findall('include'):
        name = include.findtext('name') or ''
        if name.startswith(LANDMARK_PREFIXES):
            rows.append(dict(name=name, kind='reference',
                             uri=(include.findtext('uri') or '').replace('model://', ''),
                             pose=[round(v, 3) for v in _pose(include)],
                             scale=include.findtext('scale')))
    return rows


def read_state(sdf=DEFAULT_SDF, models_dir=DEFAULT_MODELS):
    sdf = Path(sdf)
    data = sdf.read_bytes()
    world = ET.parse(sdf).getroot().find('world')
    if world is None:
        raise ValueError('SDF 缺少 <world>：%s' % sdf)
    robots = read_robots(world)
    obstacles, roads, missing = read_statics(world, models_dir, sdf)
    landmarks = read_landmarks(world)
    by_kind = {}
    for robot in robots:
        row = by_kind.setdefault(robot['kind'], dict(count=0, envelope_size=None,
                                                     sample=None, can_climb=robot['can_climb']))
        row['count'] += 1
        if row['envelope_size'] is None and robot['envelope_size']:
            row['envelope_size'] = robot['envelope_size']
            row['sample'] = robot['name']
    xs = [p[0] for o in obstacles + roads for p in o['polygon']]
    ys = [p[1] for o in obstacles + roads for p in o['polygon']]
    return dict(
        source=str(sdf), sha256=hashlib.sha256(data).hexdigest(),
        sdf_version=ET.parse(sdf).getroot().get('version'),
        world=world.get('name'), unit='m',
        generated_at=datetime.now().astimezone().isoformat(),
        counts=dict(robots=len(robots), obstacles=len(obstacles), roads=len(roads),
                    landmarks=len(landmarks), missing=len(missing)),
        bounds=(dict(x=[round(min(xs), 1), round(max(xs), 1)],
                     y=[round(min(ys), 1), round(max(ys), 1)])
                if xs and ys else None),
        fleet=by_kind, robots=robots,
        obstacles=obstacles, roads=roads, landmarks=landmarks, missing=missing,
        note=('尺寸为 SDF 碰撞几何外包络；外部模型占地仅在本地 DAE/盒体可得时登记，'
              '否则列入 missing，不臆造。'),
    )


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='提取 SDF 场景的任务规划初始状态')
    parser.add_argument('--sdf', type=Path, default=DEFAULT_SDF)
    parser.add_argument('--models', type=Path, default=DEFAULT_MODELS)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    state = read_state(args.sdf, args.models)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    if not args.quiet:
        print('SDF：%s' % state['source'])
        print('SHA-256：%s' % state['sha256'])
        print('平台 %d 台 · 障碍 %d · 道路 %d · 地标 %d · 缺几何 %d'
              % (state['counts']['robots'], state['counts']['obstacles'],
                 state['counts']['roads'], state['counts']['landmarks'],
                 state['counts']['missing']))
        for kind, row in state['fleet'].items():
            print('  %-5s %2d 台 外包络 %s 示例 %s'
                  % (kind, row['count'], row['envelope_size'], row['sample']))
        print('输出：%s' % args.out.resolve())
    return 0


if __name__ == '__main__':
    sys.exit(main())
