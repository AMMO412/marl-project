# -*- coding: utf-8 -*-
"""city_nav.py —— 城市场景的静态障碍地图、A* 路径规划与路径跟随。

这一层补的是 planning_middle_demo 与下游之间的另一段空缺：规划层只给出
"去哪个作业点"，而真实城市场景里不能沿两点直线走——建筑、街区边界都会挡路。
本文件把 simple_city 的**真实建筑碰撞体**转成二维障碍多边形，在膨胀栅格上
做 A*，再把折线路径交给闭环跟随器，输出逐拍速度指令。

数据来源与边界：
  * 障碍几何 = OSRF citysim `simple_city.world` 里各 `<include>` 的位姿 +
    本地模型 `model.sdf` 中**显式盒体碰撞**（geometry/box/size）。
  * 只接受盒体碰撞：模型用网格(mesh)做碰撞时，网格文件不在本地素材包里，
    无法得到可信尺寸——这些建筑会被列进 `missing`，**不臆造**尺寸。
  * 场景坐标换算沿用 simple_city.json 的 _meta：(米 + offset) × scale。
  * 因此本模块是"已知静态地图的避障"，不是实时感知/SLAM；动态障碍由上层
    重规划或局部避让处理（见 MockFleet 的 collision guard）。

几何实现（点到多边形距离、线段相交、多边形内判定）与 A* 栅格搜索移植自
robot_navigation_lab/navigation.py，逻辑保持一致，单位换成场景单位。
"""
import heapq
import itertools
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

EPS = 1e-9

# 本地素材：优先用本目录 assets/city（自包含），缺失时退回 robot_navigation_lab
_LOCAL = Path(__file__).resolve().parent / 'assets' / 'city'
if (_LOCAL / 'simple_city.world').is_file():
    ASSET_ROOT = _LOCAL
    WORLD_PATH = _LOCAL / 'simple_city.world'
    MODELS_DIR = _LOCAL / 'models'
else:                                     # 兼容旧素材包布局
    ASSET_ROOT = (Path(__file__).resolve().parent.parent
                  / 'robot_navigation_lab' / 'assets')
    WORLD_PATH = ASSET_ROOT / 'sources' / 'simple_city.world'
    MODELS_DIR = ASSET_ROOT / 'gazebo_models'


# ------------------------------------------------------------------
# 基础几何
# ------------------------------------------------------------------
def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def point_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    u = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy)
                     / max(dx * dx + dy * dy, EPS)))
    return distance(p, (a[0] + u * dx, a[1] + u * dy))


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def intersects(a, b, c, d):
    x1, x2, x3, x4 = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    if x1 * x2 < 0 and x3 * x4 < 0:
        return True
    return any(abs(x) < EPS and point_segment(p, u, v) < EPS
               for x, p, u, v in [(x1, c, a, b), (x2, d, a, b),
                                  (x3, a, c, d), (x4, b, c, d)])


def segment_distance(a, b, c, d):
    if intersects(a, b, c, d):
        return 0.0
    return min(point_segment(a, c, d), point_segment(b, c, d),
               point_segment(c, a, b), point_segment(d, a, b))


def inside(p, poly):
    result = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if point_segment(p, a, b) < EPS:
            return True
        if (a[1] > p[1]) != (b[1] > p[1]):
            if p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
                result = not result
    return result


def polygon_area(poly):
    return 0.5 * abs(sum(a[0] * b[1] - b[0] * a[1]
                         for a, b in zip(poly, poly[1:] + poly[:1])))


# ------------------------------------------------------------------
# 从 citysim 素材解析真实障碍
# ------------------------------------------------------------------
def _pose(node, default='0 0 0 0 0 0'):
    values = [float(v) for v in (node.findtext('pose') or default).split()]
    if len(values) != 6:
        raise ValueError('位姿应为六元组：%r' % values)
    if abs(values[3]) > 1e-6 or abs(values[4]) > 1e-6:
        raise ValueError('只支持平面刚体变换（roll/pitch 必须为 0）')
    return values


def _combine(a, b):
    c, s = math.cos(a[5]), math.sin(a[5])
    return [a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1],
            a[2] + b[2], 0.0, 0.0, a[5] + b[5]]


def _box_polygon(size, transform):
    w, h = size
    c, s = math.cos(transform[5]), math.sin(transform[5])
    return [[transform[0] + c * x - s * y, transform[1] + s * x + c * y]
            for x, y in [(-w / 2, -h / 2), (w / 2, -h / 2),
                         (w / 2, h / 2), (-w / 2, h / 2)]]


def load_obstacles(world_path=WORLD_PATH, models_dir=MODELS_DIR,
                   transform=None, bounds=None, min_area=0.05):
    """解析 simple_city 中的建筑碰撞体，返回场景坐标下的障碍列表。

    transform = dict(scale, offset_x, offset_y)：米 → 场景单位。
    bounds    = [x0, y0, x1, y1]：只保留与范围相交的障碍（None 保留全部）。
    返回 dict(obstacles, missing, provenance)；missing 列出因碰撞体为网格
    而无法解析尺寸的建筑，绝不猜测。
    """
    world_path, models_dir = Path(world_path), Path(models_dir)
    if not world_path.is_file():
        raise FileNotFoundError('缺少场景文件：%s' % world_path)
    if transform is None:
        transform = dict(scale=0.35, offset_x=110.0, offset_y=137.0)
    scale = float(transform['scale'])
    ox, oy = float(transform['offset_x']), float(transform['offset_y'])

    def to_scene(p):
        return [(p[0] + ox) * scale, (p[1] + oy) * scale]

    world = ET.parse(world_path).getroot().find('world')
    grouped, missing = {}, []
    for include in world.findall('include'):
        uri = (include.findtext('uri') or '').replace('model://', '')
        source = models_dir / uri / 'model.sdf'
        if not source.is_file():
            continue                      # 本地没有该模型，不属于本图范围
        location = _pose(include)
        model = ET.parse(source).getroot().find('model')
        boxes, unsupported, tilted = [], 0, 0
        for link in model.findall('link'):
            for collision in link.findall('collision'):
                size = collision.findtext('geometry/box/size')
                if size is None:
                    unsupported += 1
                    continue
                w, h = [float(v) for v in size.split()][:2]
                try:
                    pose = _combine(_combine(_combine(location, _pose(model)),
                                             _pose(link)), _pose(collision))
                except ValueError:
                    # 倾斜构件（如屋顶）的平面投影不是它的真实占地，跳过并记账
                    tilted += 1
                    continue
                boxes.append((w, h, pose))
        if not boxes:
            missing.append(dict(model=uri, reason='碰撞体为网格，缺少本地网格文件',
                                mesh_collisions=unsupported))
            continue
        if tilted:
            missing.append(dict(model=uri, reason='部分倾斜构件未计入平面障碍',
                                tilted_collisions=tilted))
        name = include.findtext('name') or uri
        for index, (w, h, pose) in enumerate(boxes):
            poly_m = _box_polygon((w, h), pose)
            poly = [to_scene(p) for p in poly_m]
            if polygon_area(poly) < min_area:
                continue
            if bounds is not None:
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                if (max(xs) < bounds[0] or min(xs) > bounds[2]
                        or max(ys) < bounds[1] or min(ys) > bounds[3]):
                    continue
            grouped.setdefault(name, []).append(
                dict(id='%s#%d' % (name, index), polygon=poly,
                     size_m=[w, h], source_model=uri,
                     origin_m=list(pose[:2])))

    obstacles = []
    for name, parts in grouped.items():
        for part in parts:
            part['label'] = name.replace('_', ' ')
            obstacles.append(part)
    return dict(obstacles=obstacles, missing=missing,
                provenance=dict(world=str(world_path), models=str(models_dir),
                                transform=dict(scale=scale, offset_x=ox,
                                               offset_y=oy),
                                rule='仅采用 SDF 显式盒体碰撞；网格碰撞不臆造尺寸'))


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 本地加入的场景模型（`<include>` 引用的外部 model）默认放在这里
DEFAULT_MODELS_DIR = PROJECT_ROOT / '资料' / '接口说明' / 'models'

_MESH_AABB_CACHE = {}


def _rect_polygon(local_bounds, transform):
    """局部轴对齐矩形（minx,miny,maxx,maxy）→ 绕 z 旋转平移后的多边形。"""
    x0, y0, x1, y1 = local_bounds
    c, s = math.cos(transform[5]), math.sin(transform[5])
    return [[transform[0] + c * x - s * y, transform[1] + s * x + c * y]
            for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]


def mesh_aabb(dae_path):
    """COLLADA 网格在模型坐标系下的轴对齐包围盒（米）。

    只读 `<library_geometries>` 的 positions 数组，按 `<library_visual_scenes>`
    的节点变换（translate/rotate/scale/matrix）累乘；矩阵按本批 Fuel/3ds Max
    导出文件的实际写法取**行主序**（平移落在末列）。单位取 `<asset><unit>`
    的 meter 换算（这批房子是 inch，1 inch = 0.0254 m）。

    返回 dict(min=[x,y,z], max=[x,y,z], source=路径)；解析失败返回 None。
    这是"网格包围盒"近似：对斜置/曲面构件偏保守，但不臆造尺寸。
    """
    dae_path = Path(dae_path)
    key = str(dae_path)
    if key in _MESH_AABB_CACHE:
        return _MESH_AABB_CACHE[key]
    if not dae_path.is_file():
        return None
    ns = '{http://www.collada.org/2005/11/COLLADASchema}'

    def ident():
        return [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
                for i in range(4)]

    def apply(m, p):
        return [sum(m[i][k] * p[k] for k in range(3)) + m[i][3]
                for i in range(3)]

    def node_matrix(node):
        m = ident()
        for child in node:
            tag = child.tag.replace(ns, '')
            values = [float(v) for v in (child.text or '').split()]
            if tag == 'matrix' and len(values) == 16:
                m = mul(m, [[values[r * 4 + c] for c in range(4)]
                            for r in range(4)])
            elif tag == 'translate' and len(values) == 3:
                t = ident()
                t[0][3], t[1][3], t[2][3] = values
                m = mul(m, t)
            elif tag == 'rotate' and len(values) == 4:
                axis, ang = values[:3], math.radians(values[3])
                norm = math.sqrt(sum(a * a for a in axis)) or 1.0
                x, y, z = [a / norm for a in axis]
                c, s = math.cos(ang), math.sin(ang)
                r = ident()
                r[0][0], r[0][1], r[0][2] = (c + x * x * (1 - c),
                                             x * y * (1 - c) - z * s,
                                             x * z * (1 - c) + y * s)
                r[1][0], r[1][1], r[1][2] = (y * x * (1 - c) + z * s,
                                             c + y * y * (1 - c),
                                             y * z * (1 - c) - x * s)
                r[2][0], r[2][1], r[2][2] = (z * x * (1 - c) - y * s,
                                             z * y * (1 - c) + x * s,
                                             c + z * z * (1 - c))
                m = mul(m, r)
            elif tag == 'scale' and len(values) == 3:
                sc = ident()
                sc[0][0], sc[1][1], sc[2][2] = values
                m = mul(m, sc)
        return m

    try:
        root = ET.parse(dae_path).getroot()
    except ET.ParseError:
        return None
    unit = root.find(ns + 'asset/' + ns + 'unit')
    meter = float(unit.get('meter')) if unit is not None else 1.0
    geoms = {}
    for geom in root.iter(ns + 'geometry'):
        verts = []
        for fa in geom.iter(ns + 'float_array'):
            fid = fa.get('id') or ''
            if 'positions' not in fid or not fid.endswith('-array'):
                continue
            try:
                values = [float(v) for v in (fa.text or '').split()]
            except ValueError:
                continue
            if len(values) < 3 or len(values) % 3:
                continue
            verts.extend(zip(values[0::3], values[1::3], values[2::3]))
        geoms[geom.get('id')] = verts

    points = []

    def walk(node, parent):
        m = mul(parent, node_matrix(node))
        for child in node:
            tag = child.tag.replace(ns, '')
            if tag == 'node':
                walk(child, m)
            elif tag == 'instance_geometry':
                url = (child.get('url') or '').lstrip('#')
                for p in geoms.get(url, ()):
                    points.append(apply(m, p))

    scene = root.find(ns + 'library_visual_scenes')
    if scene is not None:
        for visual in scene:
            for node in visual:
                if node.tag.replace(ns, '') == 'node':
                    walk(node, ident())
    if not points:                       # 没有视觉场景时退回几何原始坐标
        for verts in geoms.values():
            points.extend(verts)
    if not points:
        return None
    xs = [p[0] * meter for p in points]
    ys = [p[1] * meter for p in points]
    zs = [p[2] * meter for p in points]
    result = dict(min=[min(xs), min(ys), min(zs)],
                  max=[max(xs), max(ys), max(zs)],
                  unit_meter=meter, vertices=len(points), source=str(dae_path))
    _MESH_AABB_CACHE[key] = result
    return result


def _model_dir(models_dir, uri):
    """`model://House 1` → 本地模型目录（找不到返回 None）。"""
    if models_dir is None or not Path(models_dir).is_dir():
        return None
    wanted = uri.replace('model://', '').strip('/')
    direct = Path(models_dir) / wanted
    if (direct / 'model.sdf').is_file():
        return direct
    lowered = wanted.lower()
    for child in Path(models_dir).iterdir():
        if child.is_dir() and child.name.lower() == lowered:
            return child
    return None


def load_sdf_obstacles(sdf_path, bounds=None, min_area=0.05,
                       transform=None, flat_top=0.2, models_dir=None):
    """解析单文件 SDF 的静态模型，返回场景坐标障碍。

    两类来源都收：
      * `<world>/<model>`：内联静态模型（container 场景的 39 个构件）。
      * `<world>/<include>`：`model://X` 外部模型，从 `models_dir` 里读本地
        `model.sdf`；盒体碰撞照旧，**网格碰撞用本地 DAE 的包围盒**近似占地
        （city_nav.mesh_aabb）。没有本地模型/网格的 include 记入 missing。

    筛选规则（不臆造）：
      * 只收 `static=true` 的模型；robot_001—050 不是静态模型，不参与。
      * 顶面高度 ≤ flat_top 的盒体/包围盒视为通行面（地面、道路、广场）。
      * 位姿带 roll/pitch 的构件跳过并记账，平面投影不是真实占地。
      * 网格占地是"轴对齐包围盒"近似，不是精确轮廓，报告中如实标注。
    """
    sdf_path = Path(sdf_path)
    if not sdf_path.is_file():
        raise FileNotFoundError('缺少场景文件：%s' % sdf_path)
    if transform is None:
        transform = dict(scale=1.0, offset_x=0.0, offset_y=0.0)
    if models_dir is None:
        models_dir = DEFAULT_MODELS_DIR
    scale = float(transform['scale'])
    ox, oy = float(transform['offset_x']), float(transform['offset_y'])
    world = ET.parse(sdf_path).getroot().find('world')
    if world is None:
        raise ValueError('SDF 里没有 <world>：%s' % sdf_path)

    obstacles, missing = [], []

    def add_footprint(name, index, poly_m, size, pose, source, method):
        """局部平面多边形 → 场景坐标；过小或越界则丢弃。"""
        poly = [((p[0] + ox) * scale, (p[1] + oy) * scale) for p in poly_m]
        if polygon_area(poly) < min_area:
            return False
        if bounds is not None:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            if (max(xs) < bounds[0] or min(xs) > bounds[2]
                    or max(ys) < bounds[1] or min(ys) > bounds[3]):
                return False
        obstacles.append(dict(
            id='%s#%d' % (name, index), polygon=poly, size_m=size,
            source_model=source, origin_m=list(pose[:2]),
            label=name.replace('_', ' '), footprint=method))
        return True

    def scan_links(model, base, name, source, model_dir=None, index_start=0):
        """读一个模型（内联或 include 的 model.sdf）的 link/collision。"""
        index, tilted, unsupported, meshes = index_start, 0, 0, 0
        model_pose = base
        try:
            model_pose = _combine(base, _pose(model))
        except ValueError:
            missing.append(dict(model=name, reason='模型位姿不是平面刚体'))
            return index
        for link in model.findall('link'):
            try:
                link_pose = _pose(link)
            except ValueError:
                tilted += 1
                continue
            for collision in link.findall('collision'):
                try:
                    pose = _combine(_combine(model_pose, link_pose),
                                    _pose(collision))
                except ValueError:
                    tilted += 1
                    continue
                size = collision.findtext('geometry/box/size')
                if size is not None:
                    try:
                        w, h, d = [float(v) for v in size.split()][:3]
                    except ValueError:
                        unsupported += 1
                        continue
                    if pose[2] + d / 2 <= flat_top:
                        continue                # 地面/道路/广场，通行面
                    if add_footprint(name, index, _box_polygon((w, h), pose),
                                     [w, h, d], pose, source, 'box'):
                        index += 1
                    continue
                uri = collision.findtext('geometry/mesh/uri')
                if uri is None:
                    unsupported += 1
                    continue
                meshes += 1
                local = Path(uri.replace('model://', ''))
                dae = model_dir / 'meshes' / local.name \
                    if model_dir is not None else None
                box = mesh_aabb(dae) if dae is not None else None
                if box is None:
                    unsupported += 1
                    continue
                raw = (collision.findtext('geometry/mesh/scale') or '1 1 1')
                try:
                    sx, sy, sz = [float(v) for v in raw.split()][:3]
                except ValueError:
                    sx = sy = sz = 1.0
                top = pose[2] + box['max'][2] * sz
                if top <= flat_top:
                    continue                    # 纯薄片网格，视作地面贴图
                local_bounds = (box['min'][0] * sx, box['min'][1] * sy,
                                box['max'][0] * sx, box['max'][1] * sy)
                size = [(box['max'][0] - box['min'][0]) * sx,
                        (box['max'][1] - box['min'][1]) * sy, top - pose[2]]
                if add_footprint(name, index,
                                 _rect_polygon(local_bounds, pose), size,
                                 pose, source, 'mesh_aabb'):
                    index += 1
        if tilted or unsupported:
            missing.append(dict(model=name, tilted_collisions=tilted,
                                unparsed_collisions=unsupported,
                                mesh_collisions=meshes,
                                reason='非盒体/倾斜构件或缺少本地网格，未计入平面障碍'))
        return index

    for model in world.findall('model'):
        if model.findtext('static') != 'true':
            continue
        name = model.get('name') or 'model'
        scan_links(model, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), name, name)

    include_used = 0
    for include in world.findall('include'):
        uri = include.findtext('uri') or ''
        name = include.findtext('name') or uri.replace('model://', '')
        try:
            base = _pose(include)
        except ValueError:
            missing.append(dict(model=name, reason='include 位姿不是平面刚体'))
            continue
        model_dir = _model_dir(models_dir, uri)
        if model_dir is None:
            missing.append(dict(model=name, uri=uri,
                                reason='本地没有该 include 的 model.sdf，未计入'))
            continue
        source = ET.parse(model_dir / 'model.sdf').getroot().find('model')
        if source is None:
            missing.append(dict(model=name, uri=uri,
                                reason='include 的 model.sdf 缺少 <model>'))
            continue
        if (source.findtext('static') or '').strip() != 'true':
            missing.append(dict(model=name, uri=uri,
                                reason='include 模型不是 static，未计入'))
            continue
        include_used += 1
        scan_links(source, base, name, uri, model_dir=model_dir)

    return dict(obstacles=obstacles, missing=missing,
                provenance=dict(world=str(sdf_path),
                                models=str(models_dir) if models_dir else None,
                                transform=dict(scale=scale, offset_x=ox,
                                               offset_y=oy),
                                includes=include_used,
                                rule='内联盒体 + include 本地 model.sdf；'
                                     '网格取 DAE 包围盒近似；顶面≤%.1fm 不作障碍'
                                     % flat_top))


def bounds_from_scenario(scenario, margin=4.0, limit=None):
    """场景里所有平台/作业点的包络 + 边距，作为可通行区域。"""
    points = [p['pos'] for p in scenario.get('platforms', [])]
    points += [j['pos'] for j in scenario.get('jobs', [])]
    if not points:
        raise ValueError('场景里没有可用于确定边界的点')
    x0 = min(p[0] for p in points) - margin
    y0 = min(p[1] for p in points) - margin
    x1 = max(p[0] for p in points) + margin
    y1 = max(p[1] for p in points) + margin
    if limit is not None:
        x0, y0 = max(x0, limit[0]), max(y0, limit[1])
        x1, y1 = min(x1, limit[2]), min(y1, limit[3])
    return [x0, y0, x1, y1]


# ------------------------------------------------------------------
# 障碍地图
# ------------------------------------------------------------------
class NavError(ValueError):
    pass


class NavMap:
    """二维静态障碍地图：间隙查询 + 膨胀栅格 A* + 路径平滑。"""

    def __init__(self, bounds, obstacles, radius=0.6, resolution=0.2):
        self.bounds = list(bounds)
        self.obstacles = list(obstacles)
        self.radius = float(radius)
        self.resolution = float(resolution)
        self._cell_cache = {}
        self._plan_count = 0
        # 预展开边与包围盒，避免每次查询都重新 zip/求 min/max
        self._edges = []
        for obstacle in self.obstacles:
            poly = obstacle['polygon']
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            edges = list(zip(poly, poly[1:] + poly[:1]))
            self._edges.append(dict(poly=poly, edges=edges,
                                    bbox=(min(xs), min(ys), max(xs), max(ys))))

    # ---- 几何查询 ----
    def clearance(self, p):
        """到最近障碍/边界的距离；点在障碍内返回 -1。"""
        x0, y0, x1, y1 = self.bounds
        result = min(p[0] - x0, x1 - p[0], p[1] - y0, y1 - p[1])
        for item in self._edges:
            if inside(p, item['poly']):
                return -1.0
            result = min(result, *(point_segment(p, a, b)
                                   for a, b in item['edges']))
        return result

    def _edge_blocked(self, a, b, r):
        """线段是否穿过膨胀障碍；端点须已确认可行（A* 内部热路径）。"""
        sx0, sx1 = (a[0], b[0]) if a[0] <= b[0] else (b[0], a[0])
        sy0, sy1 = (a[1], b[1]) if a[1] <= b[1] else (b[1], a[1])
        for item in self._edges:
            ox0, oy0, ox1, oy1 = item['bbox']
            if (sx1 < ox0 - r or sx0 > ox1 + r
                    or sy1 < oy0 - r or sy0 > oy1 + r):
                continue
            if any(segment_distance(a, b, c, d) <= r + EPS
                   for c, d in item['edges']):
                return True
        return False

    def free(self, p, radius=None):
        r = self.radius if radius is None else radius
        return (len(p) >= 2 and all(math.isfinite(v) for v in p[:2])
                and self.clearance(p) > r + EPS)

    def segment_free(self, a, b, radius=None):
        r = self.radius if radius is None else radius
        if not self.free(a, r) or not self.free(b, r):
            return False
        return not self._edge_blocked(a, b, r)

    def _link_free(self, a, b):
        """两端都已确认可通行时的快速连线检查（A* 热路径用）。"""
        return not self._edge_blocked(a, b, self.radius)

    def nearest_free(self, p, max_radius=4.0, step=0.05, radius=None):
        """作业点/出生点若落在建筑内，吸附到最近的可通行点。

        返回 (point, offset)；offset 为吸附距离（0 表示原点本就可行）。
        """
        if self.free(p, radius):
            return [float(p[0]), float(p[1])], 0.0
        angle_step = max(8, int(2 * math.pi * 0.5 / step))
        r = step
        while r <= max_radius:
            for i in range(angle_step):
                a = 2 * math.pi * i / angle_step
                q = [p[0] + r * math.cos(a), p[1] + r * math.sin(a)]
                if self.free(q, radius):
                    return q, r
            r += step
        raise NavError('nearest_free_failed')

    def is_covered(self, a, b, samples=12):
        """线段上按采样检查可通行（报告用，比精确判定保守）。"""
        return all(self.segment_free(
            [a[0] + (b[0] - a[0]) * i / samples,
             a[1] + (b[1] - a[1]) * i / samples],
            [a[0] + (b[0] - a[0]) * (i + 1) / samples,
             a[1] + (b[1] - a[1]) * (i + 1) / samples])
            for i in range(samples))

    # ---- A* ----
    def plan(self, start, goal, smooth=True, densify=0.5):
        start = [float(start[0]), float(start[1])]
        goal = [float(goal[0]), float(goal[1])]
        if not self.free(start):
            raise NavError('start_in_obstacle')
        if not self.free(goal):
            raise NavError('goal_in_obstacle')
        straight = self.segment_free(start, goal)
        if straight:
            return self._result([start, goal], straight=True, expanded=0)

        x0, y0, x1, y1 = self.bounds
        r = self.resolution
        nx, ny = math.ceil((x1 - x0) / r), math.ceil((y1 - y0) / r)

        def point(c):
            return [x0 + (c[0] + 0.5) * r, y0 + (c[1] + 0.5) * r]

        def cell(p):
            return (int((p[0] - x0) / r), int((p[1] - y0) / r))

        def valid(c):
            if not (0 <= c[0] < nx and 0 <= c[1] < ny):
                return False
            if c not in self._cell_cache:
                self._cell_cache[c] = self.free(point(c))
            return self._cell_cache[c]

        def attach(p):
            origin = cell(p)
            for delta in range(1, 9):
                options = [(origin[0] + dx, origin[1] + dy)
                           for dx in range(-delta, delta + 1)
                           for dy in range(-delta, delta + 1)]
                options.sort(key=lambda c: distance(p, point(c)))
                for c in options:
                    if valid(c) and self.segment_free(p, point(c)):
                        return c
            raise NavError('no_free_connection')

        first, last = attach(start), attach(goal)
        counter = itertools.count()
        queue = [(distance(start, goal), next(counter), first)]
        parent, cost, closed = {}, {first: 0.0}, set()
        while queue:
            _, _, current = heapq.heappop(queue)
            if current in closed:
                continue
            if current == last:
                break
            closed.add(current)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nxt = (current[0] + dx, current[1] + dy)
                if not valid(nxt) or nxt in closed:
                    continue
                if not self._link_free(point(current), point(nxt)):
                    continue
                trial = cost[current] + math.hypot(dx, dy) * r
                if trial < cost.get(nxt, math.inf):
                    cost[nxt] = trial
                    parent[nxt] = current
                    heapq.heappush(queue,
                                   (trial + distance(point(nxt), goal),
                                    next(counter), nxt))
        else:
            raise NavError('unreachable')

        chain = [last]
        while chain[-1] != first:
            chain.append(parent[chain[-1]])
        raw = [start] + [point(c) for c in reversed(chain)] + [goal]

        if smooth:
            # 捷径必须整段在膨胀地图上可通行，避免切角贴墙
            result, i = [raw[0]], 0
            while i < len(raw) - 1:
                j = len(raw) - 1
                while j > i + 1 and not self._link_free(raw[i], raw[j]):
                    j -= 1
                result.append(raw[j])
                i = j
            raw = result
        if densify and densify > 0:
            dense = [raw[0]]
            for a, b in zip(raw, raw[1:]):
                steps = max(1, int(math.ceil(distance(a, b) / densify)))
                for k in range(1, steps + 1):
                    dense.append([a[0] + (b[0] - a[0]) * k / steps,
                                  a[1] + (b[1] - a[1]) * k / steps])
            raw = dense
        return self._result(raw, straight=False, expanded=len(closed))

    def _result(self, path, straight, expanded):
        self._plan_count += 1
        length = sum(distance(a, b) for a, b in zip(path, path[1:]))
        clearances = [self.clearance(p) for p in path]
        return dict(path=path, straight_line_ok=straight,
                    length=round(length, 3),
                    straight_length=round(distance(path[0], path[-1]), 3),
                    min_clearance=round(min(clearances), 3),
                    expanded=expanded, plan_id=self._plan_count)


# ------------------------------------------------------------------
# 路径跟随（纯追踪 + 前向安全投影）
# ------------------------------------------------------------------
@dataclass
class FollowState:
    index: int = 0
    done: bool = False
    replan: bool = False


class PathFollower:
    """把折线路径翻译成逐拍 (linear, angular)，与 motion.GoalController 同接口。

    与 GoalController 的差别：它只瞄准**下一个航点**，这里沿路径取前瞻点，
    所以绕障时不会因为"看到终点"而切角穿墙。
    """

    def __init__(self, max_linear=0.8, max_angular=1.2, lookahead=1.0,
                 goal_tol=0.25, waypoint_tol=0.35, k_angular=1.8):
        self.max_linear = float(max_linear)
        self.max_angular = float(max_angular)
        self.lookahead = float(lookahead)
        self.goal_tol = float(goal_tol)
        self.waypoint_tol = float(waypoint_tol)
        self.k_angular = float(k_angular)

    def reset(self):
        return FollowState()

    def step(self, pose, path, state, nav=None):
        """pose=(x,y,yaw)；返回 (linear, angular, state)。

        linear/angular 单位为场景单位/拍、rad/拍。到达终点时置 done。
        前瞻点取"路径上 lookahead 范围内、且从当前位姿直线可达的最远点"，
        避免在拐角处瞄准墙后的点而切角撞墙。
        """
        if not path:
            state.done = True
            return 0.0, 0.0, state
        x, y, yaw = pose
        # 推进已越过的航点
        while (state.index < len(path) - 1
               and distance((x, y), path[state.index]) < self.waypoint_tol):
            state.index += 1
        if (state.index >= len(path) - 1
                and distance((x, y), path[-1]) < self.goal_tol):
            state.done = True
            return 0.0, 0.0, state

        # 视线可达的前瞻点
        target = path[state.index]
        travelled = 0.0
        j = state.index
        while j < len(path) - 1 and travelled < self.lookahead:
            travelled += distance(path[j], path[j + 1])
            j += 1
            if nav is None or nav.segment_free((x, y), path[j]):
                target = path[j]
        dist = distance((x, y), target)
        dx, dy = target[0] - x, target[1] - y
        bearing = math.atan2(dy, dx) if (abs(dx) + abs(dy)) > EPS else yaw
        err = math.atan2(math.sin(bearing - yaw), math.cos(bearing - yaw))
        angular = max(-self.max_angular, min(self.max_angular,
                                             self.k_angular * err))
        if abs(err) > math.pi / 2:
            linear = 0.0
        else:
            linear = min(self.max_linear,
                         self.max_linear * max(0.25, min(1.0, dist / 1.2)))
            linear *= max(0.0, math.cos(err))
        if nav is not None and linear > 0:
            # 前向安全投影：贴墙时先转再走，并标记需要重规划
            projected = (x + linear * math.cos(yaw) * 0.3,
                         y + linear * math.sin(yaw) * 0.3)
            if not nav.free(projected, nav.radius * 0.75):
                state.replan = True
                linear = 0.0
        return linear, angular, state


def follow_path(nav, start_pose, path, speed=0.8, dt=0.1, max_steps=4000):
    """离线预演一条路径（测试/报告用），返回逐拍轨迹与统计。"""
    follower = PathFollower(max_linear=speed)
    state = follower.reset()
    x, y, yaw = start_pose if len(start_pose) == 3 else (*start_pose[:2], 0.0)
    trace, t = [], 0.0
    replans = 0
    for _ in range(max_steps):
        v, w, state = follower.step((x, y, yaw), path, state, nav)
        trace.append(dict(t=round(t, 3), x=round(x, 3), y=round(y, 3),
                          yaw=round(yaw, 3), v=round(v, 3), w=round(w, 3),
                          clearance=round(nav.clearance((x, y)), 3)))
        if state.done:
            break
        if state.replan and replans < 20:
            # 局部安全投影被触发：从当前位姿重新规划剩余路径
            try:
                segment = nav.plan((x, y), path[-1])['path']
                path, state, replans = segment, follower.reset(), replans + 1
                continue
            except NavError:
                state.replan = False
        state.replan = False
        yaw += w * dt
        x += v * math.cos(yaw) * dt
        y += v * math.sin(yaw) * dt
        t += dt
    return dict(trace=trace, arrived=state.done, steps=len(trace),
                duration=round(t, 3), replans=replans,
                min_clearance=round(min(p['clearance'] for p in trace), 3))


def build_nav(scenario, radius=None, resolution=0.2, margin=4.0,
              transform=None):
    """由场景 JSON 直接构造 NavMap（坐标换算取场景 _meta）。

    两种障碍来源：
      * `_meta.sdf` 存在 → 解析该单文件 SDF 的内联静态模型（新场景）；
      * 否则沿用 simple_city 的 `<include>` + 本地 model.sdf 流程。
    """
    meta = scenario.get('_meta', {})
    sdf = meta.get('sdf')
    if sdf:
        path = Path(sdf)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if transform is None:
            transform = dict(scale=meta.get('scale', 1.0),
                             offset_x=meta.get('offset_x', 0.0),
                             offset_y=meta.get('offset_y', 0.0))
        bounds = meta.get('bounds') or bounds_from_scenario(scenario, margin=margin)
        models_dir = meta.get('models')
        if models_dir:
            models_dir = Path(models_dir)
            if not models_dir.is_absolute():
                models_dir = PROJECT_ROOT / models_dir
        loaded = load_sdf_obstacles(path, bounds=bounds, transform=transform,
                                    models_dir=models_dir)
        loaded['provenance']['bounds'] = list(bounds)
        return NavMap(bounds, loaded['obstacles'],
                      radius=(meta.get('radius', 1.75)
                              if radius is None else radius),
                      resolution=meta.get('resolution', resolution)), loaded
    if transform is None:
        transform = dict(scale=meta.get('scale', 0.35),
                         offset_x=meta.get('offset_x', 110.0),
                         offset_y=meta.get('offset_y', 137.0))
    bounds = bounds_from_scenario(scenario, margin=margin)
    loaded = load_obstacles(transform=transform, bounds=bounds)
    return NavMap(bounds, loaded['obstacles'],
                  radius=0.6 if radius is None else radius,
                  resolution=resolution), loaded


if __name__ == '__main__':
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    root = Path(__file__).resolve().parent
    scenario = json.loads((root / 'scenarios/simple_city.json')
                          .read_text(encoding='utf-8'))
    nav, loaded = build_nav(scenario)
    print('边界', nav.bounds, '障碍', len(nav.obstacles), '缺几何', len(loaded['missing']))
    for o in nav.obstacles:
        print(' ', o['id'], [round(v, 2) for v in o['polygon'][0]],
              '尺寸m', o['size_m'])
    for job in scenario['jobs']:
        p, off = nav.nearest_free(job['pos'])
        if off:
            print('作业点吸附', job['job_id'], job['pos'], '->', [round(v, 2) for v in p])
