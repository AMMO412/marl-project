"""Local teaching console. Commands execute the Python navigation program."""
import argparse
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
import time
from urllib.parse import unquote,urlsplit

from navigation import Inspector,NavigationError
from run_lesson import ROOT,run,export


class Lesson:
    def __init__(self,backend,speed):
        self.backend=backend;self.speed=speed;self.lock=threading.Lock()
        self.scene=json.loads((ROOT/'scenes/city_shops.json').read_text(encoding='utf-8'))
        self.worker=None;self.reset()

    def reset(self):
        self.status='idle';self.action='run';self.frame=None;self.path=[];self.trail=[]
        self.report=None;self.error=None;self.url=None;self.started=0

    def snapshot(self):
        with self.lock:
            return dict(status=self.status,action=self.action,frame=self.frame,path=self.path,
                        trail=list(self.trail),report=self.report,error=self.error,replay=self.url,
                        elapsed=round(time.monotonic()-self.started,1) if self.started else 0,
                        backend=self.backend,application='robot_navigation_lab')

    def command(self,value):
        kind=value.get('kind')
        if kind=='navigate':command=dict(kind=kind,goal=value.get('goal'))
        elif kind=='inspection':command=dict(kind=kind,**self.scene['inspection']);command['rounds']=value.get('rounds',2)
        else:raise NavigationError('kind must be navigate or inspection')
        # Reject malformed/overlapping/blocked commands before starting any simulator.
        Inspector(self.scene).submit(command)
        with self.lock:
            if self.status=='running':raise NavigationError('robot_busy')
            self.reset();self.status='running';self.started=time.monotonic()
            self.worker=threading.Thread(target=self.execute,args=(command,),daemon=False)
            self.worker.start()

    def set_control(self,action):
        if action not in ('run','pause','cancel'):raise ValueError('unknown control action')
        with self.lock:
            if self.status!='running':raise NavigationError('no_active_command')
            self.action=action

    def get_control(self):
        with self.lock:return self.action

    def update(self,frame,path):
        with self.lock:
            self.frame=frame;self.path=path
            if not self.trail or frame['t']-self.trail[-1][2]>=.2:
                self.trail.append([frame['x'],frame['y'],frame['t']])
        # Pace only the 2D backend for watching a live execution; physics uses its own clock.
        if self.backend=='kinematic':time.sleep(.05/self.speed)

    def execute(self,command):
        output=ROOT/'outputs'/datetime.now().strftime('live_%Y%m%d_%H%M%S_%f')
        output.mkdir(parents=True,exist_ok=False)
        try:
            report,frames,events=run(self.scene,command,self.backend,output,on_frame=self.update,control=self.get_control)
            export(output,self.scene,command,self.backend,report,frames,events)
            with self.lock:self.report=report;self.status='finished';self.url='/outputs/'+output.name+'/index.html'
        except Exception as exc:
            (output/'error.txt').write_text(str(exc),encoding='utf-8')
            with self.lock:self.error=str(exc);self.status='error'


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def respond(self,status,value,kind='application/json; charset=utf-8'):
        data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',kind)
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

    def do_GET(self):
        route=unquote(urlsplit(self.path).path)
        if route=='/api/state':return self.respond(200,self.server.lesson.snapshot())
        if route=='/api/scene':return self.respond(200,self.server.lesson.scene)
        if route=='/':path=ROOT/'live.html'
        elif route.startswith('/outputs/'):
            path=(ROOT/route.lstrip('/')).resolve()
            if not path.is_relative_to((ROOT/'outputs').resolve()):return self.respond(403,dict(error='path_forbidden'))
        else:return self.respond(404,dict(error='not_found'))
        if not path.is_file():return self.respond(404,dict(error='not_found'))
        self.respond(200,path.read_bytes(),(mimetypes.guess_type(str(path))[0] or 'application/octet-stream')+'; charset=utf-8')

    def do_POST(self):
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+self.headers.get('Host',''):return self.respond(403,dict(error='origin_forbidden'))
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=4096:raise ValueError('invalid request length')
            if self.headers.get_content_type()!='application/json':raise ValueError('JSON required')
            value=json.loads(self.rfile.read(length),parse_constant=lambda x:(_ for _ in ()).throw(ValueError('finite JSON numbers required')))
            if not isinstance(value,dict):raise ValueError('JSON object required')
            if self.path=='/api/command':self.server.lesson.command(value)
            elif self.path=='/api/control':self.server.lesson.set_control(value.get('action'))
            elif self.path=='/api/shutdown':
                self.respond(200,dict(ok=True))
                threading.Thread(target=self.server.shutdown,daemon=True).start();return
            else:return self.respond(404,dict(error='not_found'))
        except (NavigationError,ValueError,TypeError,KeyError) as exc:return self.respond(400,dict(error=str(exc)))
        self.respond(200,dict(ok=True))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['kinematic','gazebo'],default='kinematic')
    parser.add_argument('--port',type=int,default=8787);parser.add_argument('--speed',type=float,default=4)
    args=parser.parse_args()
    if not 0<args.speed<=16:parser.error('speed must be in (0,16]')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.lesson=Lesson(args.backend,args.speed)
    print(f'Robot navigation lesson: http://127.0.0.1:{args.port} ({args.backend})',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        with server.lesson.lock:server.lesson.action='cancel'
        if server.lesson.worker is not None:server.lesson.worker.join(timeout=12)
        server.server_close()


if __name__=='__main__':main()
