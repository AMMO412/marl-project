"""Inspect downloaded SDF sources; Python 3.8+ standard library only.

This reads XML declarations. It does not run Gazebo, resolve arbitrary SDF
frame graphs, decode meshes, or infer vehicle performance from geometry.
"""
import argparse
import csv
import hashlib
import html
import json
import math
import re
from pathlib import Path
import xml.etree.ElementTree as ET


BASE = Path(__file__).resolve().parent


def read_xml(data):
    # Some upstream examples put shell --options in XML comments. XML forbids
    # double hyphens inside comments. Ignore comments in memory; keep source intact.
    comments = re.findall(br'<!--(.*?)-->', data, flags=re.S)
    ignored_invalid_comments = any(b'--' in c for c in comments)
    return ET.fromstring(re.sub(br'<!--.*?-->', b'', data, flags=re.S)), ignored_invalid_comments


def txt(node, path, default=None):
    value = node.findtext(path)
    return value.strip() if value is not None else default


def number(value):
    return float(value) if value is not None else None


def xml_data(node):
    """Preserve repeated XML children, attributes and scalar strings."""
    if not list(node):
        return {"attributes": node.attrib, "value": (node.text or "").strip()} if node.attrib else (node.text or "").strip()
    result = {"@attributes": node.attrib} if node.attrib else {}
    for child in node:
        result.setdefault(child.tag, []).append(xml_data(child))
    return result


def pose_data(node, parent_frame):
    p = node.find('pose')
    raw = txt(node, 'pose', '0 0 0 0 0 0')
    a = p.attrib if p is not None else {}
    values = [float(v) for v in raw.split()]
    supported = len(values) == 6 and a.get('rotation_format', 'euler_rpy') == 'euler_rpy'
    if supported and a.get('degrees', 'false').lower() in ('true', '1'):
        values = values[:3] + [math.radians(v) for v in values[3:]]
    frame = a.get('relative_to') or a.get('frame') or parent_frame
    return dict(raw=raw, attributes=a, xyz_m=values[:3], rpy_rad=values[3:] if supported else None,
                expressed_in=frame, supported=supported, used_default=p is None)


def classify(name, uri):
    s = (name + ' ' + (uri or '')).lower()
    for label, keys in [('terrain', ['terrain','ground','plane','asphalt']),
                        ('building', ['house','apartment','station','school','store','hotel','office','building','warehouse','industrial']),
                        ('shelf', ['shelf']), ('obstacle', ['clutter','bucket','trash','obstacle','stairs','barrier','cone','barrel','box'])]:
        if any(k in s for k in keys):
            return label
    return 'other'


def write_csv(path, rows, columns=None):
    if columns is None:
        columns = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict,list)) else v for k,v in row.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, help='Inspect one local SDF/world instead of the downloaded collection')
    parser.add_argument('--out', type=Path, default=BASE / 'parsed')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((BASE / 'source_manifest.json').read_text(encoding='utf-8'))
    provenance = {(BASE / f['local_path']).resolve(): f for f in manifest['files']}
    source_paths = [args.file.resolve()] if args.file else sorted((BASE / 'sources').rglob('*.sdf')) + sorted((BASE / 'sources').rglob('*.world'))
    # Build an index only for this snapshot. No network access or host model cache.
    model_index = {}
    for p in (BASE / 'sources').rglob('model.sdf'):
        repo = p.relative_to(BASE / 'sources').parts[0]
        model_index[(repo, p.parent.name)] = p.resolve()

    def resolve(uri, repo):
        if not uri or not uri.startswith('model://'):
            return None
        return model_index.get((repo, uri[8:].split('/')[0]))

    def mass_inventory(model, repo, seen):
        values = [number(txt(l, 'inertial/mass')) for l in model.findall('link')]
        masses = [v for v in values if v is not None]
        missing = [l.get('name') for l in model.findall('link') if txt(l,'inertial/mass') is None]
        unresolved = []
        for child in model.findall('model'):
            sub = mass_inventory(child, repo, seen)
            masses.append(sub['explicit_mass_sum_kg'])
            missing.extend(sub['links_without_explicit_mass'])
            unresolved.extend(sub['unresolved_model_includes'])
        for inc in model.findall('include'):
            uri = txt(inc, 'uri'); target = resolve(uri,repo)
            if target is None or target in seen:
                unresolved.append(uri)
                continue
            for child in read_xml(target.read_bytes())[0].findall('model'):
                sub = mass_inventory(child, repo, seen | {target})
                masses.append(sub['explicit_mass_sum_kg'])
                missing.extend(sub['links_without_explicit_mass'])
                unresolved.extend(sub['unresolved_model_includes'])
        return dict(explicit_mass_sum_kg=sum(masses), links_without_explicit_mass=missing,
                    unresolved_model_includes=unresolved,
                    complete_explicit_link_mass_inventory=not missing and not unresolved)

    scenes, models, entities, roads, geometries, dependencies, verification = [], [], [], [], [], [], []
    for path in source_paths:
        data = path.read_bytes()
        r, ignored_invalid_comments = read_xml(data)
        prov = provenance.get(path.resolve(), {})
        repo = prov.get('id', 'external')
        try:
            relative = path.relative_to(BASE).as_posix()
        except ValueError:
            relative = str(path)
        file_id = relative
        local_blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        verification.append(dict(file=file_id, sha256=hashlib.sha256(data).hexdigest(),
            ignored_invalid_xml_comments=ignored_invalid_comments,
            github_blob_sha=prov.get('github_blob_sha'), local_git_blob_sha=local_blob,
            matches_github_blob=local_blob==prov.get('github_blob_sha')))
        for inc in r.findall('.//include'):
            uri = txt(inc,'uri'); target = resolve(uri, repo)
            dependencies.append(dict(source_file=file_id, kind='model_include', uri=uri,
                resolved_local=str(target.relative_to(BASE)) if target else None))
        for uri in r.findall('.//uri'):
            value = (uri.text or '').strip()
            dependencies.append(dict(source_file=file_id, kind='resource_uri', uri=value,
                resolved_local=None, note='Mesh, texture and material availability is not certified by this parser'))
        for w in r.findall('world'):
            scene_id = repo + ':' + w.get('name','') + ':' + path.stem
            world_name = w.get('name', 'world')
            rows=[]
            # Only declarations directly under world. Saved <state> poses are not initial geometry.
            for obj in list(w):
                if obj.tag not in ('model','include'):
                    continue
                uri=txt(obj,'uri') if obj.tag=='include' else txt(obj,'include/uri')
                name=obj.get('name') or txt(obj,'name') or (uri or 'unnamed').rsplit('/',1)[-1]
                p=pose_data(obj,world_name)
                is_world=p['supported'] and p['expressed_in'] in (world_name,'world','__world__') and obj.find('placement_frame') is None
                vals=p['xyz_m'] + (p['rpy_rad'] or [None]*3)
                row=dict(scene=scene_id,source_file=file_id,name=name,kind=obj.tag,
                    category_hint=classify(name,uri),uri=uri,x_m=vals[0],y_m=vals[1],z_m=vals[2],
                    roll_rad=vals[3],pitch_rad=vals[4],yaw_rad=vals[5],
                    frame=p['expressed_in'],world_model_origin=is_world,pose_raw=p['raw'],
                    note='Model/include origin; not an obstacle boundary. Category inferred from name.')
                rows.append(row);entities.append(row)
            scene_roads=[]
            for road in w.findall('road'):
                row=dict(scene=scene_id,source_file=file_id,name=road.get('name'),width_m=number(txt(road,'width')),
                    points_xyz_m=[[float(v) for v in (pt.text or '').split()] for pt in road.findall('point')],
                    note='Declared road ribbon; does not establish collision geometry or a routable lane network.')
                scene_roads.append(row);roads.append(row)
            scenes.append(dict(id=scene_id,source_file=file_id,source_url=prov.get('source_url'),
                sdf_version=r.get('version'),physics=[xml_data(p) for p in w.findall('physics')],
                gravity=txt(w,'gravity'),spherical_coordinates=xml_data(w.find('spherical_coordinates')) if w.find('spherical_coordinates') is not None else None,
                declared_objects=len(rows),road_count=len(scene_roads)))
        for model in r.findall('.//model'):
            # ET's .//model includes direct root models and world models, not external includes.
            name=model.get('name','unnamed')
            if repo == 'gz' and ((path.stem == 'diff_drive' and name == 'vehicle_blue') or
                                 (path.stem == 'tracked_vehicle_simple' and name == 'simple_tracked')):
                target_dir = out / 'robot_models' / name
                target_dir.mkdir(parents=True, exist_ok=True)
                standalone = ET.Element('sdf', version=r.get('version', '1.6'))
                standalone.append(model)
                (target_dir / 'model.sdf').write_bytes(ET.tostring(standalone, encoding='utf-8', xml_declaration=True))
                (target_dir / 'model.config').write_text('<model><name>{}</name><version>1.0</version><sdf version="{}">model.sdf</sdf><description>Extracted from official gz-sim example; see provenance.json.</description></model>'.format(name,r.get('version','1.6')), encoding='utf-8')
                (target_dir / 'provenance.json').write_text(json.dumps(dict(source_file=file_id,
                    source_url=prov.get('source_url'),upstream_model_name=name,
                    changes='XML serialization and extraction only; comments omitted; parameters unchanged',
                    license_file='sources/gz/LICENSE',runtime_verified=False),ensure_ascii=False,indent=2),encoding='utf-8')
            mass=mass_inventory(model,repo,{path.resolve()})
            record=dict(source_file=file_id,source_url=prov.get('source_url'),model=name,
                static=txt(model,'static'),mass_inventory=mass,links=[],plugins=[],sensors=[],joints=[])
            for l in model.findall('link'):
                record['links'].append(dict(name=l.get('name'),mass_kg=number(txt(l,'inertial/mass')),
                    inertia=xml_data(l.find('inertial/inertia')) if l.find('inertial/inertia') is not None else None,
                    gravity=txt(l,'gravity'),pose=pose_data(l,name)))
                for kind in ('collision','visual'):
                    for shape in l.findall(kind):
                        g=shape.find('geometry')
                        if g is not None:
                            geometries.append(dict(source_file=file_id,model=name,link=l.get('name'),kind=kind,
                                name=shape.get('name'),link_pose=pose_data(l,name),shape_pose=pose_data(shape,l.get('name')),
                                geometry=xml_data(g),note='Local geometry declaration. Mesh bounds and full frame transforms not computed.'))
                for s in l.findall('sensor'):
                    record['sensors'].append(dict(link=l.get('name'),name=s.get('name'),type=s.get('type'),
                        update_rate_hz=number(txt(s,'update_rate')),configuration=xml_data(s)))
            record['plugins']=[dict(filename=p.get('filename'),name=p.get('name'),configuration=xml_data(p)) for p in model.findall('plugin')]
            record['joints']=[dict(name=j.get('name'),type=j.get('type'),configuration=xml_data(j)) for j in model.findall('joint')]
            models.append(record)
    result=dict(status='static XML inspection only; no Gazebo runtime validation',scenes=scenes,models=models,
                geometries=geometries,dependencies=dependencies,verification=verification)
    (out/'asset_inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    write_csv(out/'scene_objects.csv',entities)
    write_csv(out/'roads.csv',roads)
    write_csv(out/'geometry.csv',geometries)
    write_csv(out/'model_summary.csv',[dict(file=m['source_file'],model=m['model'],
        explicit_mass_kg=m['mass_inventory']['explicit_mass_sum_kg'],complete_mass=m['mass_inventory']['complete_explicit_link_mass_inventory'],
        sensor_count=len(m['sensors']),plugin_names=[p['name'] for p in m['plugins']]) for m in models])
    # A map of declared origins, deliberately not an occupancy map.
    blocks=[]
    for scene in scenes:
        selected=[e for e in entities if e['scene']==scene['id'] and e['world_model_origin']]
        selected_roads=[r for r in roads if r['scene']==scene['id']]
        coords=[(e['x_m'],e['y_m']) for e in selected]
        coords += [(p[0],p[1]) for r in selected_roads for p in r['points_xyz_m']]
        if not coords: continue
        lo_x=min(x for x,y in coords); hi_x=max(x for x,y in coords);lo_y=min(y for x,y in coords);hi_y=max(y for x,y in coords)
        span=max(hi_x-lo_x,hi_y-lo_y,4)*1.12;mid_x=(lo_x+hi_x)/2;mid_y=(lo_y+hi_y)/2
        vx=mid_x-span/2;vy=-mid_y-span/2;radius=span/180
        shapes=[]
        for road in selected_roads:
            points=' '.join('{},{}'.format(p[0],-p[1]) for p in road['points_xyz_m'])
            shapes.append('<polyline points="{}" fill="none" stroke="#c6cdd5" stroke-width="{}"><title>{}</title></polyline>'.format(points,road['width_m'],html.escape(road['name'])))
        colors={'shelf':'#1e8b63','building':'#a354ba','obstacle':'#db7625','terrain':'#7c8997','other':'#297cbb'}
        for e in selected:
            tooltip='{}\nx={} m, y={} m, z={} m\nyaw={} rad\n{}'.format(e['name'],e['x_m'],e['y_m'],e['z_m'],e['yaw_rad'],e['uri'] or '')
            shapes.append('<circle cx="{}" cy="{}" r="{}" fill="{}" opacity="0.8"><title>{}</title></circle>'.format(e['x_m'],-e['y_m'],radius,colors[e['category_hint']],html.escape(tooltip)))
        blocks.append('<section><h2>{}</h2><p>{} 个声明原点，{} 段道路。鼠标悬停查看名称与三维坐标。横轴 X 向右，纵轴 Y 向上。</p><svg viewBox="{} {} {} {}" role="img">{}</svg></section>'.format(html.escape(scene['id']),len(selected),len(selected_roads),vx,vy,span,span,''.join(shapes)))
    page='<!doctype html><html lang="zh"><meta charset="utf-8"><title>Gazebo 场景坐标核对</title><style>body{font-family:system-ui;background:#f3f5f7;color:#152333;margin:32px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:24px}section{background:white;padding:24px;border-radius:12px}h2{font-size:18px}p{line-height:1.7}svg{background:#f8fafb;width:100%;max-height:650px}header{max-width:1100px}</style><header><h1>Gazebo 场景坐标核对</h1><p>来自 2026-10-26 下载的固定版本源码。彩色点是模型原点，不代表碰撞轮廓或可通行区域；灰线是道路声明。绿色为货架，紫色为建筑名称提示，橙色为障碍物名称提示。分类仅按名称推断。</p></header><main>'+''.join(blocks)+'</main></html>'
    (out/'scene_map.html').write_text(page,encoding='utf-8')
    summary=dict(xml_files=len(source_paths),scenes=len(scenes),scene_objects=len(entities),roads=len(roads),
                 model_declarations=len(models),geometries=len(geometries),
                 exact_source_matches=sum(v['matches_github_blob'] for v in verification),
                 scene_counts=[dict(id=s['id'],objects=s['declared_objects'],roads=s['road_count']) for s in scenes])
    (out/'inspection_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
