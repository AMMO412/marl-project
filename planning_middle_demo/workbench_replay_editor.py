"""Reconstruct a saved playback tick, then branch its remaining simulation.

Replay the original inputs and earlier edits through the same simulator. This
retains in-flight commands, behavior state, completed work and the return origin;
starting a fresh scenario from interpolated map positions would lose that state.
"""
from copy import deepcopy
import hashlib
import json
import math

from workbench_live import LiveRun
from motion import MOTION_MODEL


SEED_FILE = '.replay_seed.json'


class PlaybackReached(Exception):
    pass


def snapshot_token(config, revision):
    data = {k: v for k, v in config.items() if k != 'snapshot_token'}
    state = json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(revision + state).hexdigest()


class ReplayRun(LiveRun):
    """Apply a saved edit immediately after its playback tick; never wall-clock pace."""
    def __init__(self, directory, scenario, config, history, capture=None, edit=None):
        super().__init__(directory, scenario, tick_seconds=0, config=config)
        self.persist_history = False
        self.history = deepcopy(history)
        self.capture = capture
        self.edit = deepcopy(edit)
        self.snapshot_revision = (hashlib.sha256((directory / 'manifest.json').read_bytes()).digest()
                                  if capture is not None else None)
        self.result = None
        self.applied = 0

    def __call__(self, core, fleet, tick):
        for item in self.history:
            if item['at_s'] == tick:
                self.paused = True
                self._apply(dict(item['changes'], revision=self.revision, sim_s=tick),
                            core, fleet, tick + 1)
                self.applied += 1
        if tick != self.capture:
            return
        self._verify_prefix(core, tick)
        self.result = deepcopy(self._snapshot(core, fleet, tick + 1)['config'])
        self.result['playback'] = True
        self.result['snapshot_token'] = snapshot_token(self.result, self.snapshot_revision)
        if self.edit is not None:
            if self.edit.get('snapshot_token') != self.result['snapshot_token']:
                raise ValueError('回放状态已变化，请重新打开编辑配置')
            self.paused = True
            self._apply(dict(self.edit, revision=self.revision, sim_s=tick),
                        core, fleet, tick + 1)
        raise PlaybackReached()


    def _verify_prefix(self, core, tick):
        path = self.directory / 'trace.jsonl'
        if not path.is_file():
            return
        original = [json.loads(line) for line in path.read_text(encoding='utf8').splitlines() if line.strip()]
        def signature(rows):
            result=[]
            for row in rows:
                if row.get('kind') != 'feedback_applied' or row.get('sim_s',0) > tick:
                    continue
                event=row['event']
                data={key:event.get(key) for key in ('command_id','job_id','worker_id','attempt','status','phase','progress','pos','z','yaw')}
                result.append((row['sim_s'],data))
            return result
        if signature(original) != signature(core.audit):
            raise ValueError('该历史运行无法按当前运动版本准确恢复；原回放保留，请新建一轮后编辑')


def load_seed(directory):
    def read(name):
        return json.loads((directory / name).read_text(encoding='utf-8-sig'))
    if (directory / SEED_FILE).is_file():
        seed = read(SEED_FILE)
        has_air = any(31 <= p.get('robot_no', 0) <= 50
                      for p in seed['scenario'].get('platforms', []))
        if has_air and seed.get('motion_model') != MOTION_MODEL:
            raise ValueError('这条回放使用旧版空中运动逻辑。请重新运行该场景，'
                             '再暂停编辑；原回放仍可播放')
        return seed
    scenario, manifest = read('scenario.json'), read('manifest.json')
    if not scenario.get('_meta', {}).get('interop'):
        raise ValueError('该历史记录没有融合任务输入，请先新建一轮融合场景规划')
    trace = (directory / 'trace.jsonl').read_text(encoding='utf-8')
    if any(json.loads(line).get('kind') == 'config_updated'
           for line in trace.splitlines() if line.strip()):
        raise ValueError('该旧记录未保存编辑前的初始状态，请重新运行场景后编辑回放')
    return dict(scenario=scenario, config=manifest['workbench_config'], history=[],
                motion_model=MOTION_MODEL, verify_saved_prefix=True)


def run_seed(seed, directory, capture=None, edit=None, recorder=None):
    from interop.message import parse_message
    from interop.runtime import InteropPlanner, nav_from_scenario
    from run_demo_v2 import simulate
    scenario = deepcopy(seed['scenario'])
    bundle = scenario['_meta']['interop']
    parsed = parse_message(bundle['message'], bundle['formation'])
    config = seed['config']
    planner = InteropPlanner(parsed, objective=config['objective'], data=scenario)
    if recorder is not None:
        recorder.planner = planner
    hook = ReplayRun(directory, scenario, config, seed['history'], capture, edit)
    nav = nav_from_scenario(parsed) if config['avoid'] else None
    def before_tick(core, fleet, now):
        if recorder is not None and not getattr(recorder, '_attached', False):
            recorder.attach(core, fleet)
            recorder._attached = True

    try:
        report, audit = simulate(scenario, mode=config['mode'], motion=config['motion'],
                                 avoid=config['avoid'], behavior=config['behavior'],
                                 max_ticks=config['max_ticks'], planner=planner, nav=nav,
                                 after_tick=hook, before_tick=before_tick,
                                 run_id=directory.name)
    except PlaybackReached:
        return hook.result
    if capture is not None:
        raise ValueError('该时刻超出实际仿真范围，请选择时间轴内的时刻')
    if hook.applied != len(seed['history']):
        raise ValueError('重规划未到达全部编辑时刻')
    return scenario, parsed if not hook.revision else planner.scenario, report, audit


def playback_config(directory, at_s):
    if isinstance(at_s, bool):
        raise ValueError('回放时刻必须是有效数字')
    try:
        value = float(at_s)
    except (ValueError, TypeError):
        raise ValueError('回放时刻必须是有效数字') from None
    if not math.isfinite(value) or value < 0:
        raise ValueError('回放时刻必须是非负有限数字')
    tick = math.floor(value)
    seed = load_seed(directory)
    # Later edits belong to the abandoned future, not this branch.
    seed['history'] = [e for e in seed['history'] if e['at_s'] <= tick]
    result = run_seed(seed, directory, capture=tick)
    result['preset'] = seed['config']['scenario']
    result['max_ticks'] = seed['config']['max_ticks']
    # Preset/horizon are presentation fields; the token covers runtime state.
    return result


def prepare_branch(directory, payload):
    if not isinstance(payload, dict):
        raise ValueError('无效的回放编辑配置')
    required = {'source_run', 'sim_s', 'snapshot_token', 'tasks', 'units',
                'exclude_tasks', 'delete_tasks'}
    allowed = required | {'targets', 'observation_targets', 'target_library'}
    if set(payload) - allowed or not required <= payload.keys():
        raise ValueError('回放编辑缺少时刻、状态标识、任务或平台配置')
    tick = payload['sim_s']
    if type(tick) is not int or tick < 0:
        raise ValueError('回放编辑使用非负整数仿真时刻')
    seed = load_seed(directory)
    seed['history'] = [e for e in seed['history'] if e['at_s'] <= tick]
    # Full validation/cancellation preflight in an isolated reconstruction.
    run_seed(seed, directory, capture=tick, edit=payload)
    changes = {k: deepcopy(payload[k]) for k in
               ('tasks', 'units', 'exclude_tasks', 'delete_tasks')}
    for key in ('targets', 'observation_targets', 'target_library'):
        if key in payload:
            changes[key] = deepcopy(payload[key])
    seed['history'].append(dict(at_s=tick, changes=changes))
    return seed
