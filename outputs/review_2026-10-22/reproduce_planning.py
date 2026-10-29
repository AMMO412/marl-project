"""Read-only, generic correctness probes; no project source is modified."""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "planning"))
from contract import Platform, Task, GroupSnapshot, Assignment, Plan, sample_scenario
from executor import StubExecutor
import planner
from metrics import ConflictTracker
from run_flow import deviation


def emit(name, **data):
    print(json.dumps(dict(probe=name, **data), ensure_ascii=False))


def platform(pid="P", pos=(0, 0), battery=1000, speed=1, rate=1, payload=8):
    return Platform(pid, "generic", pos, battery, payload, speed, rate, "generic")


def task(tid="T", pos=(0, 0), work=5, window=(0, 100), crew=1, payload=0):
    return Task(tid, "generic", pos, work, window, crew, payload, None)


def snapshot(ps, ts):
    return GroupSnapshot(1, 0, "makespan", ps, ts)


def overlaps(pl):
    out = []
    by_pid = {}
    for a in pl.assignments:
        for pid in a.pids:
            by_pid.setdefault(pid, []).append((a.start, a.end, a.tid))
    for pid, spans in by_pid.items():
        spans.sort()
        for left, right in zip(spans, spans[1:]):
            if right[0] < left[1]:
                out.append(dict(pid=pid, left=left, right=right))
    return out


def main():
    p, t = platform(), task(window=(10, 20))
    pl, ev = planner.plan(snapshot([p], [t]), 0, H=100)
    emit("window_lower_bound", window=t.window,
         assignments=[a.__dict__ for a in pl.assignments])

    p, t = platform(pos=(0, 0), battery=100), task(pos=(10, 0), work=1)
    snap = snapshot([p], [t])
    pl, _ = planner.plan(snap, 0, H=100)
    start = pl.assignments[0].start
    ex = StubExecutor()
    for now in range(start + 1):
        ex.step(pl, snap, now)
    emit("travel_energy_missing", planned_travel=10, battery_consumed=100-p.battery,
         status=t.status, position=p.pos)

    p, t = platform(battery=0), task(work=1, crew=2)
    snap = snapshot([p], [t])
    pl = Plan(0, 0, 10, 1, "probe", "makespan", [Assignment("T", ["P"], 0, 1, 0)])
    StubExecutor().step(pl, snap, 0)
    emit("executor_gate", battery=p.battery, crew_required=t.crew,
         crew_actual=1, status=t.status, progress=t.progress)

    ps = [platform("P0", battery=6), platform("P1", battery=6)]
    t = task(work=10, crew=2)
    pl, ev = planner.plan(snapshot(ps, [t]), 0, H=100)
    emit("cooperative_battery_false_rejection", joint_duration=5,
         batteries=[p.battery for p in ps], assignments=len(pl.assignments),
         rejected=pl.rejected, events=ev)

    p, t = platform(payload=8), task(payload=4)
    snap = snapshot([p], [t])
    old, _ = planner.plan(snap, 0, H=100)
    p.payload = 0
    new, _ = planner.plan(snap, 1, H=100, prev_plan=old)
    emit("commitment_bypasses_gate", feasible_now=planner.feasible(p, t)[0],
         assignments=[a.__dict__ for a in new.assignments])

    tracker = ConflictTracker()
    tracker.observe([dict(kind="conflict", tid="T", type="overlap"),
                     dict(kind="resolved", tid="T", type="overlap", by="shift")], 0)
    tracker.observe([dict(kind="conflict", tid="T", type="overlap"),
                     dict(kind="resolved", tid="T", type="overlap", by="defer")], 5)
    emit("recurring_conflict_remains_resolved", report=tracker.report())

    tracker = ConflictTracker()
    tracker.observe([dict(kind="conflict", tid="T", type="crew_short"),
                     dict(kind="resolved", tid="T", type="crew_short", by="defer")], 0)
    tracker.observe([dict(kind="filter", feasible_pairs=0, rejected_pairs=1)], 5)
    emit("no_candidates_counted_as_resolved", report=tracker.report())

    # A timeout whose remaining work is smaller than dev_threshold=4.
    t = task(work=5)
    t.progress = 4
    pl = Plan(0, 0, 10, 1, "probe", "makespan", [Assignment("T", ["P"], 0, 5, 0)])
    emit("timeout_below_threshold", deviation=deviation(pl, snapshot([platform()], [t]), 5),
         default_threshold=4)

    for horizon in (20, 45, 100):
        failures = []
        for seed in range(100):
            pl, _ = planner.plan(sample_scenario(seed=seed), 0, H=horizon)
            bad = overlaps(pl)
            if bad:
                failures.append(dict(seed=seed, overlap=bad))
        emit("generated_scenario_overlaps", horizon=horizon, seeds=100,
             affected=len(failures), first=failures[:1])

    # Search deterministic synthetic instances omitted by the existing suite.
    for case in range(10000):
        rng = random.Random(case)
        ps = [platform("P%d" % i, (rng.randrange(10), rng.randrange(10)),
                       rate=rng.choice([0.5, 1, 2]), payload=rng.choice([2, 4, 8]))
              for i in range(4)]
        ts = [task("T%d" % i, (rng.randrange(10), rng.randrange(10)),
                   rng.randrange(2, 20), (0, 1000), rng.randrange(1, 4),
                   rng.choice([0, 2, 4])) for i in range(6)]
        snap = snapshot(ps, ts)
        pl, ev = planner.plan(snap, 0, H=1000)
        bad = overlaps(pl)
        if bad:
            emit("serial_schedule_overlap", case=case, overlap=bad,
                 platforms=[p.__dict__ for p in ps], tasks=[t.__dict__ for t in ts],
                 assignments=[a.__dict__ for a in pl.assignments], events=ev)
            break
    else:
        emit("serial_schedule_overlap", result="none in 10000 cases")


if __name__ == "__main__":
    main()
