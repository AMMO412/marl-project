"""Run an independent civilian navigation command and export measured trace.

Windows: py -3.14 robot_navigation_lab/run_lesson.py --backend kinematic
WSL: /usr/bin/python3 .../run_lesson.py --backend gazebo
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from navigation import Inspector,Pose,integrate,distance,NavigationError

ROOT=Path(__file__).resolve().parent


def run(scene,command,backend,output,max_sim_s=600,on_frame=None,control=None):
    executor=Inspector(scene);frames=[];started=time.monotonic();contacts=None;sensor_advertised=None
    def apply_control():
        if control is None:return
        action=control()
        if action=='cancel':executor.cancel()
        elif action=='pause':executor.pause()
        else:executor.resume()
    def capture(v,w):
        frame=dict(executor.snapshot(),linear=v,angular=w);frames.append(frame)
        if on_frame is not None:on_frame(frame,executor.path)
    if backend=='kinematic':
        pose=Pose(*scene['robot']['start']);executor.submit(command,pose)
        for step in range(int(max_sim_s/.05)+1):
            t=step*.05;apply_control();v,w=executor.update(pose,t)
            capture(v,w)
            if executor.state in executor.TERMINAL:break
            new=integrate(pose,v,w,.05)
            if not executor.world.segment_free(pose.xy(),new.xy(),scene['robot']['radius']):
                executor.fail('swept_collision');break
            pose=new
    elif backend=='gazebo':
        from gazebo_backend import Gazebo
        with Gazebo(scene,output) as gazebo:
            t0,pose=gazebo.feedback();last=t0;executor.submit(command,pose)
            while True:
                actual,pose=gazebo.feedback(after=last);last=actual
                t=actual-t0
                apply_control();v,w=executor.update(pose,t)
                capture(v,w)
                gazebo.command(v,w)
                if executor.state in executor.TERMINAL or t>=max_sim_s:break
                if time.monotonic()-started>240:executor.fail('wall_clock_timeout');break
            sensor_advertised='/lesson/body_contacts' in gazebo.node.topic_list()
            contacts=gazebo.obstacle_contacts if sensor_advertised else None
    else:raise ValueError('unknown backend')
    if executor.state not in executor.TERMINAL:executor.fail('simulation_budget_exceeded')
    if frames and frames[-1]['state']!=executor.state:capture(0.,0.)
    total=sum(distance([a['x'],a['y']],[b['x'],b['y']]) for a,b in zip(frames,frames[1:]))
    report=dict(backend=backend,physical_simulation=backend=='gazebo',state=executor.state,
                error=executor.error,rounds_completed=executor.round,goal=executor.goal,
                final_pose=[executor.last_pose.x,executor.last_pose.y,executor.last_pose.yaw],
                simulated_s=round(executor.time,3),wall_s=round(time.monotonic()-started,2),
                distance_m=round(total,3),min_body_clearance_m=round(min(f['clearance'] for f in frames),4),
                obstacle_contacts=contacts,contact_sensor_advertised=sensor_advertised,
                contact_scope='robot base collision vs shops; wheel/caster contacts not counted',
                plans=executor.path_version,visits=executor.visits,
                sample_count=len(frames),geometry_scope=scene['scope'],
                perception='known static collision map; no lidar or unknown/dynamic obstacle sensing',
                independent_lesson=True)
    return report,frames,executor.events


def export(output,scene,command,backend,report,frames,events):
    for name,value in [('scene.json',scene),('command.json',command),('report.json',report),
                       ('events.json',events)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'trace.jsonl').open('w',encoding='utf-8') as h:
        for frame in frames:h.write(json.dumps(frame,ensure_ascii=False)+'\n')
    manifest=dict(backend=backend,generated_at=datetime.now().astimezone().isoformat(),
                  source_sha256=hashlib.sha256((ROOT/'scenes/city_shops.json').read_bytes()).hexdigest(),
                  independent_lesson=True,physical_simulation=backend=='gazebo')
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    render(output,scene,command,report,frames,events)


def render(output,scene,command,report,frames,events):
    """Refresh only the view from saved evidence without rerunning execution."""
    template=(ROOT/'player.html').read_text(encoding='utf-8')
    data=json.dumps(dict(scene=scene,command=command,report=report,frames=frames,events=events),ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    (output/'index.html').write_text(template.replace('__NAVIGATION_DATA__',data),encoding='utf-8')


def main():
    import sys
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['kinematic','gazebo'],default='kinematic')
    parser.add_argument('--kind',choices=['inspection','navigate'],default='inspection')
    parser.add_argument('--goal',nargs=2,type=float,default=[22,9.356])
    parser.add_argument('--rounds',type=int,default=2)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    scene=json.loads((ROOT/'scenes/city_shops.json').read_text(encoding='utf-8'))
    command=dict(kind='inspection',**scene['inspection']) if args.kind=='inspection' else dict(kind='navigate',goal=args.goal)
    if args.kind=='inspection':command['rounds']=args.rounds
    output=args.out or ROOT/'outputs'/datetime.now().strftime('run_%Y%m%d_%H%M%S_%f')
    output.mkdir(parents=True,exist_ok=False)
    try:
        report,frames,events=run(scene,command,args.backend,output)
        export(output,scene,command,args.backend,report,frames,events)
    except (RuntimeError,NavigationError,TimeoutError) as exc:
        (output/'error.txt').write_text(str(exc),encoding='utf-8');raise
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('导航回放：'+str((output/'index.html').resolve()))
    return 0 if report['state']=='complete' else 2


if __name__=='__main__':raise SystemExit(main())
