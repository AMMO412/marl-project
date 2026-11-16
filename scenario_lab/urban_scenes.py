"""Standalone synthetic urban maps and neutral mobile-robot inspection cases.

Standard library only. Does not import or change the task/combat planning stack.
"""
import argparse
from collections import defaultdict
import hashlib
import heapq
import json
import math
from pathlib import Path
import random
import xml.etree.ElementTree as ET

PRESETS = {
    'residential': ('住宅街区', 800, 800, 6, 6, 11),
    'downtown': ('密集城区', 1200, 1000, 9, 8, 23),
    'mixed': ('公园与斜街混合片区', 1600, 1200, 10, 8, 37),
}


def axes(size, count, rng, uneven=False):
    weights = [rng.uniform(.7, 1.3) if uneven else 1 for _ in range(count)]
    total = sum(weights)
    values = [36.0]
    for weight in weights:
        values.append(round(values[-1] + (size - 72) * weight / total, 3))
    return values


def box_polygon(box):
    x, y, w, h = box
    return [[x-w/2, y-h/2], [x+w/2, y-h/2], [x+w/2, y+h/2], [x-w/2, y+h/2], [x-w/2, y-h/2]]


def intersects(a, b, box, padding=0):
    """Exact segment versus expanded axis-aligned rectangle."""
    x, y, w, h = box
    low, high = 0., 1.
    for start, delta, lower, upper in ((a[0], b[0]-a[0], x-w/2-padding, x+w/2+padding),
                                       (a[1], b[1]-a[1], y-h/2-padding, y+h/2+padding)):
        if abs(delta) < 1e-12:
            if not lower <= start <= upper:
                return False
        else:
            p, q = sorted(((lower-start)/delta, (upper-start)/delta))
            low, high = max(low, p), min(high, q)
            if low > high:
                return False
    return True


def make_map(kind):
    label, width, height, nx, ny, seed = PRESETS[kind]
    rng = random.Random(seed)
    xs, ys = axes(width, nx, rng, kind == 'mixed'), axes(height, ny, rng, kind == 'mixed')
    nodes = [[x, y] for y in ys for x in xs]
    def node(i, j):
        return j * len(xs) + i
    roads = []
    def road(a, b, road_width, role):
        roads.append(dict(id='RD%03d' % len(roads), a=a, b=b, width_m=road_width, role=role))
    for j in range(ny+1):
        for i in range(nx):
            road(node(i,j), node(i+1,j), 24 if j % 3 == 0 else 14, '主街' if j % 3 == 0 else '支街')
    for i in range(nx+1):
        for j in range(ny):
            road(node(i,j), node(i,j+1), 26 if i % 3 == 0 else 14, '主街' if i % 3 == 0 else '支街')
    if kind == 'mixed':
        for i in range(min(nx, ny)):
            road(node(i,i), node(i+1,i+1), 22, '斜向大道')
    buildings, parks, obstacles, trees = [], [], [], []
    for j in range(ny):
        for i in range(nx):
            x0, x1, y0, y1 = xs[i]+22, xs[i+1]-22, ys[j]+22, ys[j+1]-22
            if rng.random() < (.20 if kind == 'mixed' else .10):
                parks.append(dict(id='PK%d' % len(parks), box=[(x0+x1)/2,(y0+y1)/2,x1-x0,y1-y0]))
                for _ in range(8):
                    trees.append([round(rng.uniform(x0,x1),2), round(rng.uniform(y0,y1),2)])
                continue
            cols, rows = (rng.choice([2,3,4]), rng.choice([2,3])) if kind == 'downtown' else (rng.choice([2,3]),rng.choice([1,2,3]))
            dx, dy = (x1-x0)/cols, (y1-y0)/rows
            for iy in range(rows):
                for ix in range(cols):
                    box = [round(x0+(ix+.5)*dx,2), round(y0+(iy+.5)*dy,2),
                           round(dx*rng.uniform(.65,.90),2), round(dy*rng.uniform(.60,.88),2)]
                    if any(intersects(nodes[r['a']],nodes[r['b']],box,r['width_m']/2+2) for r in roads):
                        continue
                    buildings.append(dict(id='B%04d' % len(buildings),box=box,
                                          height_m=rng.choice([8,12,18,25,35,50]),
                                          category=rng.choice(['住宅','办公','商铺'])))
    # Street furniture is outside road center corridors, never used as a navigation shortcut.
    for r in roads:
        if rng.random() > .65:
            continue
        a, b = nodes[r['a']], nodes[r['b']]
        vx, vy = b[0]-a[0], b[1]-a[1]
        if abs(vx)>1e-9 and abs(vy)>1e-9:
            continue
        for fraction in (.3,.7):
            x, y = a[0]+fraction*vx, a[1]+fraction*vy
            offset = r['width_m']/2+3
            x, y = (x,y+offset) if vx else (x+offset,y)
            box=[round(x,2),round(y,2),7 if vx else 2.5,2.5 if vx else 7]
            if any(intersects(nodes[q['a']],nodes[q['b']],box,2) for q in roads):
                continue
            if any(intersects((x,y),(x,y),p['box'],4) for p in buildings):
                continue
            obstacles.append(dict(id='OB%03d'%len(obstacles),box=box,height_m=1.4,category='路侧障碍'))
    data=dict(schema='neutral-urban-map/v1',id=kind,label=label,seed=seed,units='m',
              bounds=[0,0,width,height],nodes=nodes,roads=roads,buildings=buildings,
              parks=parks,trees=trees,obstacles=obstacles,synthetic=True)
    data['sha256']=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    return data


def graph(data):
    result=defaultdict(list)
    for r in data['roads']:
        a,b=r['a'],r['b'];distance=math.dist(data['nodes'][a],data['nodes'][b])
        result[a].append((b,distance));result[b].append((a,distance))
    return result


def shortest(data, adjacency, start, end):
    queue=[(0,start)];cost={start:0};parent={}
    while queue:
        value,node=heapq.heappop(queue)
        if value!=cost[node]:continue
        if node==end:
            path=[node]
            while node!=start:node=parent[node];path.append(node)
            return value,[data['nodes'][i] for i in reversed(path)]
        for nxt,length in adjacency[node]:
            candidate=value+length
            if candidate<cost.get(nxt,math.inf):
                cost[nxt]=candidate;parent[nxt]=node;heapq.heappush(queue,(candidate,nxt))
    raise ValueError('Unreachable inspection point')


def make_case(data, seed, count=8):
    rng=random.Random(seed);adjacency=graph(data)
    width,height=data['bounds'][2:]
    eligible=[r for r in data['roads'] if all(130<p[0]<width-130 and 130<p[1]<height-130
               for p in (data['nodes'][r['a']],data['nodes'][r['b']]))]
    selected=rng.choice(eligible);a,b=data['nodes'][selected['a']],data['nodes'][selected['b']]
    center=[(a[0]+b[0])/2,(a[1]+b[1])/2];radius=min(width,height)*.19
    zone=[max(20,center[0]-radius),max(20,center[1]-radius),min(width-20,center[0]+radius),min(height-20,center[1]+radius)]
    candidates=[]
    for r in data['roads']:
        a,b=data['nodes'][r['a']],data['nodes'][r['b']]
        f=rng.uniform(.2,.8);point=[round(a[0]+(b[0]-a[0])*f,3),round(a[1]+(b[1]-a[1])*f,3)]
        if zone[0]<point[0]<zone[2] and zone[1]<point[1]<zone[3]:candidates.append((r,point))
    if len(candidates)<count:raise ValueError('Not enough inspection targets')
    targets=rng.sample(candidates,count)
    spawns=[0,len(data['nodes'])-1,len(data['nodes'])//2, len(data['nodes'])//3]
    robots=[dict(id='robot_%d'%(i+1),start=data['nodes'][n],speed_mps=3.0) for i,n in enumerate(spawns)]
    current=[(n,data['nodes'][n]) for n in spawns];clocks=[0.0]*4;routes=[];tasks=[]
    for i,(road,point) in enumerate(targets):
        robot=i%4;start_node,start_point=current[robot]
        options=[]
        for endpoint in (road['a'],road['b']):
            distance,path=shortest(data,adjacency,start_node,endpoint)
            options.append((distance+math.dist(data['nodes'][endpoint],point),endpoint,path))
        _,endpoint,path=min(options)
        # Previous target remains connected to its saved road endpoint.
        points=[start_point]+path+[point]
        points=[p for j,p in enumerate(points) if j==0 or p!=points[j-1]]
        distance=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
        arrival=clocks[robot]+distance/robots[robot]['speed_mps'];finish=arrival+8
        tasks.append(dict(id='I%d'%(i+1),type='inspection',position=point,service_s=8,window_s=[0,1800]))
        routes.append(dict(task_id='I%d'%(i+1),robot_id=robots[robot]['id'],path=points,
                           start_s=clocks[robot],arrival_s=arrival,end_s=finish,distance_m=distance))
        clocks[robot]=finish;current[robot]=(endpoint,point)
    return dict(schema='neutral-inspection/v1',map_id=data['id'],map_sha256=data['sha256'],
                seed=seed,zone=zone,robots=robots,tasks=tasks,reference_routes=routes,
                end_s=max(clocks),note='中性巡检参考：道路图最短路与轮流分配，非既有业务算法评测结果；未模拟多车互避与运动学。')


def geojson(data):
    features=[]
    for road in data['roads']:
        features.append(dict(type='Feature',properties=dict(road,kind='road'),geometry=dict(type='LineString',coordinates=[data['nodes'][road['a']],data['nodes'][road['b']]])))
    for group in ('buildings','parks','obstacles'):
        for item in data[group]:features.append(dict(type='Feature',properties=dict(item,kind=group),geometry=dict(type='Polygon',coordinates=[box_polygon(item['box'])])))
    return dict(type='FeatureCollection',name=data['id'],coordinate_system='local Cartesian metres; not longitude/latitude',features=features)


def sdf(data):
    root=ET.Element('sdf',version='1.7');world=ET.SubElement(root,'world',name=data['id'])
    light=ET.SubElement(world,'light',name='daylight',type='directional')
    ET.SubElement(light,'direction').text='-.4 -.6 -1'
    ET.SubElement(light,'diffuse').text='.9 .9 .9 1'
    ET.SubElement(ET.SubElement(world,'scene'),'ambient').text='.5 .5 .5 1'
    def box(name,values,z,height,collision=True,color='.65 .66 .68 1'):
        x,y,w,h=values;model=ET.SubElement(world,'model',name=name);ET.SubElement(model,'static').text='true'
        ET.SubElement(model,'pose').text=f'{x} {y} {z} 0 0 0';link=ET.SubElement(model,'link',name='body')
        for kind in (['collision','visual'] if collision else ['visual']):
            child=ET.SubElement(link,kind,name=kind);geometry=ET.SubElement(child,'geometry');shape=ET.SubElement(geometry,'box')
            ET.SubElement(shape,'size').text=f'{w} {h} {height}'
            if kind=='visual':ET.SubElement(ET.SubElement(child,'material'),'diffuse').text=color
    w,h=data['bounds'][2:];box('ground',[w/2,h/2,w,h],-.1,.2,color='.89 .89 .85 1')
    for road in data['roads']:
        a,b=data['nodes'][road['a']],data['nodes'][road['b']];length=math.dist(a,b)
        name='road_'+road['id'];box(name,[(a[0]+b[0])/2,(a[1]+b[1])/2,length,road['width_m']],.015,.02,False,'.98 .98 .96 1')
        world[-1].find('pose').text=f'{(a[0]+b[0])/2} {(a[1]+b[1])/2} .015 0 0 {math.atan2(b[1]-a[1],b[0]-a[0])}'
    for group in ('buildings','obstacles'):
        for item in data[group]:box(item['id'],item['box'],item['height_m']/2,item['height_m'])
    ET.indent(root);return ET.tostring(root,encoding='unicode')


def build_maps(destination):
    """Export geometry only, with no tasks or substitute algorithm results."""
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    catalog=[]
    for kind in PRESETS:
        data=make_map(kind);directory=destination/kind;directory.mkdir(exist_ok=True)
        for name,value in [('map.json',data),('map.geojson',geojson(data))]:
            (directory/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        (directory/'map.sdf').write_text(sdf(data),encoding='utf-8')
        catalog.append(dict(id=data['id'],label=data['label'],bounds=data['bounds'],
                            buildings=len(data['buildings']),roads=len(data['roads']),
                            parks=len(data['parks']),obstacles=len(data['obstacles']),sha256=data['sha256']))
    (destination/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
    return catalog


def build(destination, cases=20):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    catalog=[]
    for kind in PRESETS:
        data=make_map(kind);directory=destination/kind;directory.mkdir(exist_ok=True)
        samples=[make_case(data,seed) for seed in range(cases)]
        for name,value in [('map.json',data),('map.geojson',geojson(data))]:
            (directory/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        (directory/'map.sdf').write_text(sdf(data),encoding='utf-8')
        (directory/'cases').mkdir(exist_ok=True)
        for case in samples:(directory/'cases'/('seed_%03d.json'%case['seed'])).write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf-8')
        catalog.append(dict(map=data,cases=samples))
    viewer=Path(__file__).with_name('viewer.html').read_text(encoding='utf-8')
    (destination/'街区与随机巡检预览.html').write_text(viewer.replace('__SCENES__',json.dumps(catalog,ensure_ascii=False)),encoding='utf-8')
    stats=[dict(id=x['map']['id'],label=x['map']['label'],size_m=x['map']['bounds'][2:],buildings=len(x['map']['buildings']),roads=len(x['map']['roads']),parks=len(x['map']['parks']),obstacles=len(x['map']['obstacles']),cases=len(x['cases'])) for x in catalog]
    (destination/'catalog.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    return stats


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',default='outputs/urban_maps_20261112')
    parser.add_argument('--cases',type=int,default=20)
    parser.add_argument('--maps-only',action='store_true',help='Export map geometry only; no preview page or inspection tasks')
    parser.add_argument('--with-inspection',action='store_true',help='Explicitly generate the optional historical inspection preview')
    parser.add_argument('--map',choices=list(PRESETS));parser.add_argument('--task-seed',type=int,default=0)
    args=parser.parse_args()
    if args.maps_only or not args.with_inspection:
        print(json.dumps(build_maps(args.out),ensure_ascii=False,indent=2))
    elif args.map:
        directory=Path(args.out);directory.mkdir(parents=True,exist_ok=True)
        case=make_case(make_map(args.map),args.task_seed)
        (directory/'inspection_case.json').write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf-8')
        print(directory/'inspection_case.json')
    else:print(json.dumps(build(args.out,args.cases),ensure_ascii=False,indent=2))
