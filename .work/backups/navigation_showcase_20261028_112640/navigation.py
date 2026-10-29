"""Independent known-map mobile-robot navigation and civilian inspection lesson.

The planner computes paths from obstacle geometry; motion is driven by measured
poses (or a labelled kinematic backend), never by a prerecorded animation path.
"""
from dataclasses import dataclass
import heapq
import itertools
import math

EPS=1e-9


def distance(a,b):return math.hypot(a[0]-b[0],a[1]-b[1])
def wrap(a):return math.atan2(math.sin(a),math.cos(a))


def point_segment(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    u=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(dx*dx+dy*dy,EPS)))
    return distance(p,(a[0]+u*dx,a[1]+u*dy))


def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def intersects(a,b,c,d):
    x1,x2,x3,x4=cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)
    if x1*x2<0 and x3*x4<0:return True
    return any(abs(x)<EPS and point_segment(p,u,v)<EPS
               for x,p,u,v in [(x1,c,a,b),(x2,d,a,b),(x3,a,c,d),(x4,b,c,d)])


def segment_distance(a,b,c,d):
    if intersects(a,b,c,d):return 0.0
    return min(point_segment(a,c,d),point_segment(b,c,d),point_segment(c,a,b),point_segment(d,a,b))


def inside(p,poly):
    result=False
    for a,b in zip(poly,poly[1:]+poly[:1]):
        if point_segment(p,a,b)<EPS:return True
        if (a[1]>p[1])!=(b[1]>p[1]) and p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:
            result=not result
    return result


class NavigationError(ValueError):pass


class World:
    def __init__(self,scene):
        self.scene=scene
        self.bounds=list(scene['bounds'])
        self.obstacles=list(scene['obstacles'])
        self.revision=0

    def clearance(self,p):
        x0,y0,x1,y1=self.bounds
        result=min(p[0]-x0,x1-p[0],p[1]-y0,y1-p[1])
        for obstacle in self.obstacles:
            poly=obstacle['polygon']
            if inside(p,poly):return -1.0
            result=min(result,*(point_segment(p,a,b) for a,b in zip(poly,poly[1:]+poly[:1])))
        return result

    def free(self,p,radius):
        return len(p)>=2 and all(math.isfinite(v) for v in p[:2]) and self.clearance(p)>radius+EPS

    def segment_free(self,a,b,radius):
        if not self.free(a,radius) or not self.free(b,radius):return False
        for obstacle in self.obstacles:
            poly=obstacle['polygon']
            if any(segment_distance(a,b,c,d)<=radius+EPS for c,d in zip(poly,poly[1:]+poly[:1])):
                return False
        return True

    def add_box(self,name,center,size):
        x,y=center;w,h=size
        if w<=0 or h<=0:raise ValueError('Box size must be positive')
        self.obstacles.append(dict(id=name,label=name,polygon=[[x-w/2,y-h/2],[x+w/2,y-h/2],[x+w/2,y+h/2],[x-w/2,y+h/2]]))
        self.revision+=1


class GridPlanner:
    def __init__(self,world,radius,resolution=.25):
        self.world,self.radius,self.resolution=world,radius,resolution
        self.cache={};self.revision=-1

    def plan(self,start,goal):
        start,goal=list(start[:2]),list(goal[:2])
        if not self.world.free(start,self.radius):raise NavigationError('start_in_obstacle_or_outside_map')
        if not self.world.free(goal,self.radius):raise NavigationError('goal_in_obstacle_or_outside_map')
        if self.world.segment_free(start,goal,self.radius):return [start,goal]
        if self.revision!=self.world.revision:self.cache.clear();self.revision=self.world.revision
        x0,y0,x1,y1=self.world.bounds;r=self.resolution
        nx,ny=math.ceil((x1-x0)/r),math.ceil((y1-y0)/r)
        def point(c):return [x0+(c[0]+.5)*r,y0+(c[1]+.5)*r]
        def cell(p):return (int((p[0]-x0)/r),int((p[1]-y0)/r))
        def valid(c):
            if not (0<=c[0]<nx and 0<=c[1]<ny):return False
            if c not in self.cache:self.cache[c]=self.world.free(point(c),self.radius)
            return self.cache[c]
        def attachment(p):
            origin=cell(p)
            for delta in range(5):
                options=[(origin[0]+dx,origin[1]+dy) for dx in range(-delta,delta+1) for dy in range(-delta,delta+1)]
                options.sort(key=lambda c:distance(p,point(c)))
                for c in options:
                    if valid(c) and self.world.segment_free(p,point(c),self.radius):return c
            raise NavigationError('no_free_grid_connection')
        first,last=attachment(start),attachment(goal)
        counter=itertools.count();queue=[(distance(start,goal),next(counter),first)]
        parent={};cost={first:0};closed=set()
        while queue:
            _,_,current=heapq.heappop(queue)
            if current in closed:continue
            if current==last:break
            closed.add(current)
            for dx,dy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
                nxt=(current[0]+dx,current[1]+dy)
                if not valid(nxt) or nxt in closed:continue
                if not self.world.segment_free(point(current),point(nxt),self.radius):continue
                trial=cost[current]+math.hypot(dx,dy)*r
                if trial<cost.get(nxt,math.inf):
                    cost[nxt]=trial;parent[nxt]=current
                    heapq.heappush(queue,(trial+distance(point(nxt),goal),next(counter),nxt))
        else:raise NavigationError('unreachable')
        chain=[last]
        while chain[-1]!=first:chain.append(parent[chain[-1]])
        raw=[start]+[point(c) for c in reversed(chain)]+[goal]
        # Every shortcut is checked against inflated geometry, including corners.
        result=[raw[0]];i=0
        while i<len(raw)-1:
            j=len(raw)-1
            while j>i+1 and not self.world.segment_free(raw[i],raw[j],self.radius):j-=1
            result.append(raw[j]);i=j
        return result


@dataclass
class Pose:
    x:float
    y:float
    yaw:float=0.0
    def xy(self):return [self.x,self.y]


class Inspector:
    TERMINAL={'complete','failed','cancelled','idle'}
    def __init__(self,scene):
        self.world=World(scene);self.robot=scene['robot']
        self.planner=GridPlanner(self.world,self.robot['radius']+self.robot['clearance'],scene['grid_resolution'])
        self.state='idle';self.paused=False;self.events=[];self.path=[];self.path_index=0
        self.goal=None;self.command=None;self.round=0;self.cursor=0;self.dwell_until=None
        self.last_pose=Pose(*self.robot['start']);self.time=0.;self.error=None
        self.planned_revision=0;self.path_version=0;self.visits=[]

    def record(self,kind,**fields):self.events.append(dict(t=round(self.time,4),kind=kind,**fields))

    def submit(self,command,pose=None,t=0):
        if self.state not in self.TERMINAL:raise NavigationError('robot_busy')
        self.time=t;self.last_pose=pose or self.last_pose
        kind=command.get('kind')
        if kind not in ('navigate','inspection'):raise NavigationError('unknown_command_kind')
        if kind=='inspection':
            if type(command.get('rounds')) is not int or command['rounds']<1:raise NavigationError('rounds_must_be_positive_integer')
            if len(command.get('checkpoints',[]))<2:raise NavigationError('at_least_two_inspection_checkpoints_required')
            targets=[command['entry']]+command['checkpoints']
        else:targets=[command['goal']]
        for target in targets:
            if len(target)!=2 or not self.world.free(target,self.planner.radius):
                raise NavigationError('target_in_obstacle_or_outside_map')
        self.command=dict(command);self.round=0;self.cursor=0;self.visits=[];self.paused=False;self.error=None
        self.state='navigating_to_entry' if kind=='inspection' else 'navigating'
        self.dwell_until=None;self.record('command_accepted',command=self.command)
        try:self.set_goal(command['entry'] if kind=='inspection' else command['goal'])
        except NavigationError as exc:self.fail(str(exc))

    def set_goal(self,goal):
        self.goal=list(goal);self.path=self.planner.plan(self.last_pose.xy(),self.goal)
        self.path_index=min(1,len(self.path)-1);self.path_version+=1
        self.planned_revision=self.world.revision
        self.record('path_planned',goal=self.goal,path=self.path,path_version=self.path_version,
                    straight_line_blocked=not self.world.segment_free(self.last_pose.xy(),self.goal,self.planner.radius))

    def fail(self,reason):
        self.state='failed';self.error=reason;self.record('failed',reason=reason)

    def pause(self):
        if self.state not in self.TERMINAL and not self.paused:
            self.paused=True;self.pause_started=self.time;self.record('paused')
    def resume(self):
        if self.paused:
            if self.dwell_until is not None:self.dwell_until+=self.time-self.pause_started
            self.paused=False;self.record('resumed')
    def cancel(self):
        if self.state not in self.TERMINAL:self.state='cancelled';self.record('cancelled')

    def update(self,pose,t):
        if not math.isfinite(t) or t<self.time-EPS:raise NavigationError('non_monotonic_feedback_time')
        if not all(math.isfinite(v) for v in (pose.x,pose.y,pose.yaw)):
            raise NavigationError('non_finite_pose_feedback')
        self.last_pose=pose;self.time=t
        if self.state in self.TERMINAL or self.paused:return 0.,0.
        if not self.world.free(pose.xy(),self.robot['radius']):self.fail('measured_pose_in_collision');return 0.,0.
        if self.world.revision!=self.planned_revision:
            try:self.set_goal(self.goal);self.record('map_replanned')
            except NavigationError as exc:self.fail(str(exc));return 0.,0.
        if self.dwell_until is not None:
            if t<self.dwell_until:return 0.,0.
            self.dwell_until=None
            try:self.set_goal(self.command['checkpoints'][self.cursor%len(self.command['checkpoints'])])
            except NavigationError as exc:self.fail(str(exc));return 0.,0.
        if distance(pose.xy(),self.goal)<=self.robot['goal_tolerance']:
            self.record('goal_reached',goal=self.goal,measured_pose=pose.xy())
            if self.state=='navigating':self.state='complete';self.record('complete');return 0.,0.
            if self.state=='navigating_to_entry':
                self.state='inspecting';self.record('inspection_started')
                try:self.set_goal(self.command['checkpoints'][0])
                except NavigationError as exc:self.fail(str(exc))
                return 0.,0.
            n=len(self.command['checkpoints'])
            self.visits.append(dict(index=self.cursor%n,t=t,pose=pose.xy()))
            if self.cursor>0 and self.cursor%n==0:
                self.round+=1;self.record('round_completed',round=self.round)
            if self.round>=self.command['rounds']:
                self.state='complete';self.record('complete');return 0.,0.
            self.cursor+=1;self.dwell_until=t+float(self.command.get('dwell_s',0))
            self.record('checkpoint_visited',index=(self.cursor-1)%n,round=self.round)
            return 0.,0.
        while self.path_index<len(self.path)-1 and distance(pose.xy(),self.path[self.path_index])<self.robot['waypoint_tolerance']:
            self.path_index+=1
        target=self.path[self.path_index];d=distance(pose.xy(),target)
        error=wrap(math.atan2(target[1]-pose.y,target[0]-pose.x)-pose.yaw)
        angular=max(-self.robot['angular_speed'],min(self.robot['angular_speed'],2.0*error))
        linear=0. if abs(error)>.25 else min(self.robot['speed'],1.5*d)*max(0,math.cos(error))
        projected=[pose.x+linear*math.cos(pose.yaw)*.15,pose.y+linear*math.sin(pose.yaw)*.15]
        if not self.world.segment_free(pose.xy(),projected,self.robot['radius']+.04):
            self.fail('collision_guard_stop');return 0.,0.
        return linear,angular

    def snapshot(self):
        return dict(t=round(self.time,4),x=self.last_pose.x,y=self.last_pose.y,yaw=self.last_pose.yaw,
                    state=self.state,paused=self.paused,round=self.round,goal=self.goal,
                    path_version=self.path_version,error=self.error,
                    clearance=self.world.clearance(self.last_pose.xy())-self.robot['radius'])


def integrate(pose,linear,angular,dt):
    # Midpoint integration of a differential-drive kinematic model.
    a=pose.yaw+angular*dt/2
    return Pose(pose.x+linear*math.cos(a)*dt,pose.y+linear*math.sin(a)*dt,wrap(pose.yaw+angular*dt))
