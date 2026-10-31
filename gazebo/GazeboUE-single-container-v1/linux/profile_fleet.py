"""[PROFILE] Native Gazebo stats, /proc sampling, bounded fleet motion."""
import argparse,json,os,re,subprocess,threading,time
from pathlib import Path
import rclpy
from geometry_msgs.msg import Twist

p=argparse.ArgumentParser(); p.add_argument('output'); args=p.parse_args()
out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
instance_id=os.environ.get('GAZEBO_INSTANCE_ID','container_00')
env=dict(os.environ,IGN_PARTITION=os.environ.get('IGN_PARTITION',f'gazebo_ue_{instance_id}'))
stats=subprocess.Popen(['stdbuf','-oL','ign','topic','-e','-t',f'/world/{instance_id}/stats'],env=env,stdout=subprocess.PIPE,stderr=open(out/'stats-stderr.log','w'),text=True)
def read_stats():
    block=[]
    with (out/'gazebo-stats.jsonl').open('w',buffering=1) as log:
        for line in stats.stdout:
            if line.strip(): block.append(line); continue
            text=''.join(block); block=[]
            record={'unix':time.time(),'monotonic':time.monotonic(),'raw_monotonic':time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)/1e9}
            for key in ('sim_time','real_time'):
                match=re.search(key+r'\s*\{([^}]+)\}',text)
                if match:
                    fields=dict(re.findall(r'(sec|nsec):\s*(\d+)',match[1]))
                    record[key]=int(fields.get('sec',0))+int(fields.get('nsec',0))/1e9
            m=re.search(r'real_time_factor:\s*([\d.e+-]+)',text)
            if m: record['reported_rtf']=float(m[1])
            if 'sim_time' in record and 'real_time' in record: log.write(json.dumps(record)+'\n')
reader=threading.Thread(target=read_stats,daemon=True);reader.start()
hz=os.sysconf('SC_CLK_TCK'); page=os.sysconf('SC_PAGE_SIZE')
def resources():
    groups={name:{'cpu_seconds':0,'rss_bytes':0,'pids':[]} for name in ('gazebo','ros_bridge','pose_server')}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit(): continue
        try:
            cmd=(directory/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
            if cmd.startswith('ign gazebo'): group='gazebo'
            elif '/lib/ros_gz_bridge/parameter_bridge ' in cmd: group='ros_bridge'
            elif cmd.startswith('python3 pose_server.py'): group='pose_server'
            else: continue
            fields=(directory/'stat').read_text().rsplit(')',1)[1].split()
            g=groups[group];g['cpu_seconds']+=(int(fields[11])+int(fields[12]))/hz
            g['rss_bytes']+=int(fields[21])*page;g['pids'].append(int(directory.name))
        except (OSError,ValueError): pass
    mem={k:int(v) for k,v in re.findall(r'^(\w+):\s+(\d+)',Path('/proc/meminfo').read_text(),re.M)}
    cpu=list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    return dict(unix=time.time(),monotonic=time.monotonic(),groups=groups,
                memory_total_bytes=mem['MemTotal']*1024,memory_used_bytes=(mem['MemTotal']-mem['MemAvailable'])*1024,
                cpu_total_ticks=sum(cpu),cpu_idle_ticks=cpu[3]+cpu[4],logical_cpus=os.cpu_count())
rclpy.init();node=rclpy.create_node('profile_fleet_motion')
pubs=[node.create_publisher(Twist,f'/robot_{i:03d}/cmd_vel',10) for i in range(1,51)]
(out/'linux-ready.json').write_text(json.dumps({'unix':time.time(),'pid':os.getpid()}))
try:
    deadline=time.monotonic()+180
    while not (out/'start.json').exists():
        if time.monotonic()>deadline: raise TimeoutError('Host did not start measurement')
        time.sleep(.1)
    start=time.monotonic(); next_sample=start
    with (out/'linux-resources.jsonl').open('w',buffering=1) as log:
        while not (out/'stop.json').exists() and time.monotonic()-start<90:
            now=time.monotonic()
            # Same bounded command on each independent topic; reverse every 10 wall seconds.
            msg=Twist();msg.linear.x=.1 if int((now-start)/10)%2==0 else -.1
            for pub in pubs:pub.publish(msg)
            if now>=next_sample:
                log.write(json.dumps(resources())+'\n');next_sample=now+1
            time.sleep(.1)
finally:
    for _ in range(10):
        for pub in pubs: pub.publish(Twist())
        time.sleep(.05)
    stats.terminate()
    try:stats.wait(timeout=5)
    except subprocess.TimeoutExpired:stats.kill();stats.wait()
    reader.join(timeout=2)
    node.destroy_node();rclpy.shutdown()
