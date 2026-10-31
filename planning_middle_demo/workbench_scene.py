"""Read-only SDF backdrop. Kept separate from recorded planner constraints."""
from pathlib import Path
import xml.etree.ElementTree as ET

from sdf_state import DEFAULT_SDF, DEFAULT_MODELS, read_state, _pose, _combine, _rect


def scene_map(scenario):
    meta = scenario.get('_meta') or {}
    formation = (meta.get('interop') or {}).get('formation') or {}
    fm = formation.get('meta') or {}
    if formation:
        if fm.get('scene') != 'container_00' or fm.get('source_sdf') != DEFAULT_SDF.name:
            return None
        scale, ox, oy = 1.0, 0.0, 0.0
    else:
        if Path(str(meta.get('sdf', ''))).name != DEFAULT_SDF.name:
            return None
        scale = float(meta.get('scale', 1))
        ox, oy = float(meta.get('offset_x', 0)), float(meta.get('offset_y', 0))
    state = read_state(DEFAULT_SDF, DEFAULT_MODELS)
    world = ET.parse(DEFAULT_SDF).getroot().find('world')
    surfaces = []
    for model in world.findall('model'):
        if model.get('name') != 'env_lawn_ground':
            continue
        for link in model.findall('link'):
            for visual in link.findall('visual'):
                text = visual.findtext('geometry/box/size')
                if text:
                    size = list(map(float, text.split()))
                    pose = _combine(_combine(_pose(model), _pose(link)), _pose(visual))
                    surfaces.append(dict(id=model.get('name'),
                                         polygon=_rect(size + pose[:2], pose[5])))
    def point(p):
        return [p[0] * scale + ox, p[1] * scale + oy]
    for item in state['obstacles'] + state['roads'] + surfaces:
        item['polygon'] = [point(p) for p in item['polygon']]
    for landmark in state['landmarks']:
        landmark['pose'][:2] = point(landmark['pose'])
        landmark['missing_geometry'] = any(m['name'] == landmark['name'] for m in state['missing'])
    return dict(obstacles=state['obstacles'], roads=state['roads'],
                landmarks=state['landmarks'], surfaces=surfaces,
                missing=state['missing'], sha256=state['sha256'], source=state['source'],
                note='当前 SDF 静态底图；建筑为网格外包络，缺失地形仅标位置。底图不修改本轮规划约束。')
