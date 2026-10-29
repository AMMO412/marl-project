"""Use installed WSL dependencies; no trainer is started and no source is edited."""
import ast
import importlib.util
import json
import sys
import time
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "taskalloc"))
from taskalloc_env import RLlibTaskAlloc, TASK_SPECS


def emit(name, **data):
    print(json.dumps(dict(probe=name, **data), ensure_ascii=False))


def old_env(n=1):
    env = RLlibTaskAlloc(dict(n_platforms=n, n_tasks=1, max_steps=40,
                             fixed_objective=0))
    env.reset()
    env.type_id[:n] = 0
    env.pos[:n] = 0
    env.task_pos[0] = 0
    env.battery[:n] = 1
    return env


def main():
    path = ROOT / "taskalloc" / "taskalloc_v2_env.py"
    bypassed = False
    try:
        spec = importlib.util.spec_from_file_location("v2_actual", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        emit("v2_actual_import", result="success")
    except Exception as error:
        emit("v2_actual_import", error_type=type(error).__name__, message=str(error))
        # Diagnostic bypass of ONLY the historical path-guard TypeError, in memory.
        source = path.read_text(encoding="utf-8").replace(
            "os.path.normpath(sys.path)", "[os.path.normpath(p) for p in sys.path]")
        mod = types.ModuleType("v2_diagnostic")
        mod.__file__ = str(path)
        exec(compile(source, str(path), "exec"), mod.__dict__)
        bypassed = True
    env = mod.TaskAllocV2Env(dict(n_platforms=1, n_tasks=1, max_steps=2))
    env.reset()
    t, p = env.snapshot.tasks[0], env.snapshot.platforms[0]
    t.work, t.crew, t.pos, t.need_payload = 1, 1, (0, 0), 0
    p.pos, p.work_rate, p.battery = (0, 0), 1, 100
    env.step({"platform_0": 1})
    emit("v2_id_mapping", diagnostic_import_bypass=bypassed, agent=env.agents[0],
         platform_id=p.pid, progress=t.progress, completed=env.completed,
         has_get_env_info=hasattr(env, "get_env_info"))
    try:
        info = env.get_env_info()
        emit("v2_marllib_interface", num_agents=info["num_agents"],
             episode_limit=info["episode_limit"], keys=sorted(info))
    except Exception as error:
        emit("v2_missing_marllib_interface", error_type=type(error).__name__, message=str(error))

    # Use the public agent ID to inspect the latest execution semantics.
    env = mod.TaskAllocV2Env(dict(n_platforms=1, n_tasks=1, max_steps=2))
    env.reset()
    t, p = env.snapshot.tasks[0], env.snapshot.platforms[0]
    t.work, t.crew, t.pos, t.need_payload, t.window = 1, 1, (10, 0), 0, (10, 20)
    p.pos, p.work_rate, p.battery = (0, 0), 1, 100
    env.step({env.agents[0]: 1})
    emit("v2_teleport_and_early_work", elapsed_steps=env.now,
         distance=10, speed=p.speed, window=t.window, status=t.status,
         battery_consumed=100-p.battery)

    env = old_env()
    env.task_spec[0], env.task_left[0] = 1, 2
    env.step({"platform_0": 1})
    emit("v1_window_lower_bound", now_fraction=env.step_count/env.max_steps,
         earliest=TASK_SPECS[1]["window"][0], progress=2-float(env.task_left[0]))

    env = old_env(4)
    env.type_id[:4] = np.arange(4)
    env.task_spec[0], env.task_left[0] = 2, 4
    emit("v1_colift_unreachable", required_payload=TASK_SPECS[2]["payload"],
         legal_for_each_type=[bool(env.action_mask(i)[1]) for i in range(4)])

    # Large work avoids completion mid-loop and exposes per-agent tally use.
    for n in (1, 2):
        env = old_env(n)
        env.task_spec[0], env.task_left[0] = 0, 100
        env.step({name: 1 for name in env.agents})
        emit("v1_group_work_rate", n=n, progress=100-float(env.task_left[0]),
             energy=float(env.energy_used))

    # Only the first platform has arrived. The other is still >1 unit away.
    env = old_env(2)
    env.task_spec[0], env.task_left[0] = 0, 100
    env.pos[1] = [1, 1]
    env.step({name: 1 for name in env.agents})
    emit("v1_unarrived_member_counted", progress=100-float(env.task_left[0]),
         crew_tally=int(env.crew_count[0]), second_distance=float(np.linalg.norm(env.pos[1])))

    # Load the actual evaluator's function definitions without loading a model.
    tree = ast.parse((ROOT / "taskalloc" / "eval_taskalloc.py").read_text(encoding="utf-8"))
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in ("collect_actions", "rollout")]
    ns = dict(np=np, time=time, query_actions=lambda *args: 0)
    exec(compile(ast.Module(body=funcs, type_ignores=[]), "eval_taskalloc.py", "exec"), ns)
    env = RLlibTaskAlloc(dict(n_platforms=2, n_tasks=1, max_steps=1, seed=321))
    a, frames_a = ns["rollout"](env, None, "shared", 1000, "random", env.agents, False, None)
    b, frames_b = ns["rollout"](env, None, "shared", 1000, "model", env.agents, False, None)
    emit("evaluation_is_not_paired", csv_seed_a=a["seed"], csv_seed_b=b["seed"],
         initial_positions_equal=bool(np.array_equal(frames_a[0][0], frames_b[0][0])),
         initial_tasks_equal=bool(np.array_equal(frames_a[0][1], frames_b[0][1])))


if __name__ == "__main__":
    main()
