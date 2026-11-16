"""Live IPC and transactional publication of same-ID replay continuations."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4


def live_trace_window(rows, now, seconds=20):
    """Bound live pose history; disk archives and saved playback stay complete."""
    recent, latest = [], {}
    sampled = {'behavior_detail', 'behavior_samples', 'approach_route', 'return_sample',
               'air_wait_sample', 'recon_target_sample', 'relay_target_sample'}
    for index, row in enumerate(rows):
        event = row.get('event') or {}
        kind = row.get('kind')
        key = None
        if kind == 'feedback_applied':
            key = (kind, event.get('worker_id'))
        elif kind == 'behavior_event' and event.get('kind') in sampled:
            route = event.get('route') or {}
            key = (event.get('kind'), event.get('job_id'), event.get('pid') or route.get('pid'))
        if key is None or row.get('sim_s', 0) >= now - seconds:
            recent.append((index, row))
        else:
            latest[key] = (index, row)
    return [row for _, row in sorted([*latest.values(), *recent], key=lambda item: item[0])]


class SessionWorkbench:
    @property
    def _backend(self):
        return sys.modules[type(self).__module__]

    def status(self):
        with self.lock:
            if self.process is None:
                return None
            code = self.process.poll()
            if code is not None and self.pending_replan is not None:
                self._finish_replan(code)
            if code == 0 and self.process_error:
                code = 1
            return dict(id=self.current, state='running' if code is None else
                ('complete' if code == 0 else 'error'), exit_code=code,
                live=self.live, replacing=self.pending_replan is not None,
                stopping=bool(getattr(self,'stop_requested',False)) and code is None,
                error=self.process_error)

    def start_replay(self, data):
        from workbench_replay_editor import prepare_branch, SEED_FILE
        if set(data) != {'replay_edit'}:
            raise ValueError('续算配置只接受 replay_edit')
        payload = data['replay_edit']
        if not isinstance(payload, dict):
            raise ValueError('无效的续算配置')
        backend = self._backend
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError('已有仿真正在运行，请先结束或暂停编辑当前实时运行')
            self.status()
            original = backend.run_path(payload.get('source_run', ''))
            previous = (original / 'manifest.json').read_bytes()
            seed = prepare_branch(original, payload)
            seed['config'] = dict(seed['config'], live=False)
            stage = original.parent / '.replans' / uuid4().hex / original.name
            stage.mkdir(parents=True, exist_ok=False)
            for name,value in [(SEED_FILE,seed),('request.json',seed['config'])]:
                (stage/name).write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf8')
            with (stage/'worker.log').open('w',encoding='utf8') as log:
                process = subprocess.Popen([sys.executable,'-X','utf8',str(Path(backend.__file__).resolve()),
                    '--worker',str(stage)],stdout=log,stderr=log,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.process, self.current, self.live = process, original.name, False
            self.pending_replan = stage, original, previous
            self.process_error = None
            self.stop_requested = False
            threading.Thread(target=self._wait_for_replan,args=(process,),daemon=True).start()
            return self.status()

    def _wait_for_replan(self, process):
        process.wait()
        with self.lock:
            if self.process is process:
                self.status()

    def _finish_replan(self, code):
        stage, original, previous = self.pending_replan
        self.pending_replan = None
        backend = self._backend
        try:
            if code:
                log=(stage/'worker.log').read_text(encoding='utf8',errors='replace')
                raise ValueError(log.strip().splitlines()[-1] if log.strip() else '续算进程失败')
            from chain_trace import verify_chain
            if not verify_chain(stage)['passed']:
                raise ValueError('续算归档未通过全链路校验')
            if (original/'manifest.json').read_bytes() != previous:
                raise ValueError('原运行已更新，请重新打开编辑器')
            manifest=backend.read_json(stage/'manifest.json')
            manifest['scenario']=str(original/'input_message.json')
            for key,name in [('message','input_message.json'),('formation','input_formation.json')]:
                manifest['inputs'][key]=str(original/name)
            backup=original.parent/'.run_revisions'/original.name/(datetime.now().strftime('%Y%m%d_%H%M%S_')+uuid4().hex[:8])
            backup.parent.mkdir(parents=True,exist_ok=True)
            manifest['continuation']=dict(previous_manifest_sha256=hashlib.sha256(previous).hexdigest(),
                previous_revision=str(backup),run_id=original.name)
            (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
            original.rename(backup)
            try:
                stage.rename(original)
            except OSError:
                backup.rename(original)
                raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.process_error='原运行保留，续算未发布：'+str(exc)

    def live_state(self, run_id):
        from workbench_live import read_json as read_live_json
        if self.current != run_id or not self.live:
            raise ValueError('这轮运行没有开启实时编辑')
        path = self._backend.run_path(run_id) / '.live_state.json'
        state = read_live_json(path) if path.is_file() else None
        return dict(process=self.status(), state=state)

    def live_view(self, run_id, cursor=None):
        from workbench_live import read_json as read_live_json
        result = self.live_state(run_id)
        snapshot = result['state']
        if snapshot is None:
            return dict(process=result['process'], view=None)
        version = '%s:%s:%s:%s' % (snapshot['config']['sim_s'], snapshot['revision'],
                                    snapshot['audit_count'], int(snapshot['paused']))
        if cursor == version:
            return dict(process=result['process'], version=version, view=None)
        out = self._backend.run_path(run_id)
        trace = []
        try:
            scenario = read_live_json(out / '.live_scene.json')
            if snapshot['audit_count']:
                from itertools import islice
                with (out / '.live_trace.jsonl').open(encoding='utf-8') as stream:
                    trace = [json.loads(line) for line in islice(stream, snapshot['audit_count'])]
        except FileNotFoundError:
            if (out / 'trajectory.html').is_file():
                return dict(process=result['process'], version=version, view=None)
            raise
        scenario['jobs'] = snapshot['scene_jobs']
        scenario['_meta']['interop'] = dict(message=snapshot['config']['message'],
            formation=snapshot['config']['formation'])
        known = {row['robot_no'] for row in scenario.get('platforms', [])}
        for unit in snapshot['config']['formation']['formation']['units']:
            if unit['robot_id'] not in known:
                point = unit['position']
                scenario['platforms'].append(dict(robot_no=unit['robot_id'],
                    pos=[point['x'], point['y']], z=unit.get('altitude_m', 0)))
        # The next tick's configuration can be staged before its motion step.
        # Keep the visible playhead at the last completed simulation step.
        trace = [row for row in trace if row['sim_s'] <= snapshot['config']['sim_s']]
        trace = live_trace_window(trace, snapshot['config']['sim_s'])
        report = snapshot['report']
        report['behavior_details'] = any(
            row['kind'] == 'behavior_event' and row['event'].get('kind') == 'behavior_detail'
            for row in trace)
        view = self._backend.run_view(run_id, out, scenario, report, trace)
        current_pids = {row['pid'] for row in report['platforms']}
        view['replay']['workers'] = [row for row in view['replay']['workers']
                                     if row['pid'] in current_pids]
        view['live'] = dict(paused=snapshot['paused'], revision=snapshot['revision'],
                                trail_window_s=20,
                            assignments=snapshot['assignments'],
                            sim_s=snapshot['config']['sim_s'])
        return dict(process=result['process'], version=version, view=view)

    def live_command(self, run_id, payload):
        with self.live_lock:
            return self._live_command(run_id, payload)

    def _live_command(self, run_id, payload):
        from workbench_live import read_json as read_live_json, write_json
        if not isinstance(payload, dict) or payload.get('action') not in ('pause', 'resume', 'apply', 'stop'):
            raise ValueError('无效的实时操作')
        with self.lock:
            if (self.current != run_id or not self.live or self.process is None
                    or self.process.poll() is not None):
                raise RuntimeError('实时仿真已经结束')
            directory = self._backend.run_path(run_id)
            request = directory / '.live_request.json'
            if request.exists():
                raise RuntimeError('上一条实时操作正在处理')
            token = uuid4().hex
            process = self.process
            write_json(request, dict(payload, id=token))
            if payload['action'] == 'stop':
                self.stop_requested = True
                return dict(stopping=True, request_id=token)
        reply_path = directory / '.live_reply.json'
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if reply_path.is_file():
                reply = read_live_json(reply_path)
                if reply['id'] == token:
                    if reply['error'] is not None:
                        raise ValueError(reply['error'])
                    return reply['state']
            if process.poll() is not None:
                raise RuntimeError('仿真已结束，请查看运行结果')
            time.sleep(0.05)
        raise RuntimeError('仿真尚未确认操作，请刷新实时状态')
