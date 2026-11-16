# -*- coding: utf-8 -*-
"""在途抵达判定：持续移动不算"到不了"，真正停住才改派。

回归背景：旧口径只看 ``now > planned_start + 30``，长距离接近/绕障/低加速度
起步会被误判为 arrival_timeout，产生与输入事件无关的改派记录。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts_v2 import PROTOCOL_V2, Command, Job
from coordinator_v2 import CoordinatorV2


def _core():
    scenario = dict(protocol=PROTOCOL_V2, objective="makespan",
                    platforms=[dict(robot_no=1, pos=[0.0, 0.0])], jobs=[])
    return CoordinatorV2(scenario, run_id="case-v2", motion="real")


def _job(core):
    job = Job(job_id="T1", jtype="recon", pos=(100.0, 0.0), work=100.0,
              window=(0, 400), crew=1, need_payload=0.0, need_sensor=None)
    job.status = "assigned"
    job.attempts = 1
    core.jobs[job.job_id] = job
    command = Command(command_id="case-v2:T1:1:rover_01", job_id="T1",
                      worker_id="rover_01", attempt=1, issued_sim_s=0,
                      start_sim_s=0, expected_end_sim_s=100,
                      task=dict(work_start_s=0), delivery={})
    core.active[command.command_id] = command
    core.platform_cmd["rover_01"] = command.command_id
    meta = dict(subtask_id="T1-S1", task_type="T-RCN", role="search:1",
                target={"point": [100.0, 0.0]}, start_s=0, end_s=100,
                duration_s=100, window_end_s=400)
    core._register_subtask(job, meta, "rover_01", command)
    return job, command


def _feedback(core, command, now, x):
    event = dict(protocol=PROTOCOL_V2, run_id=core.run_id,
                 event_id="ev-%d" % now, command_id=command.command_id,
                 job_id=command.job_id, worker_id=command.worker_id,
                 attempt=1, sim_s=now, status="progress",
                 progress=float(now), subtask_progress=min(1.0, now / 100.0),
                 phase="travel", pos=[float(x), 0.0])
    core.receive(event, now)


class ArrivalWatchTests(unittest.TestCase):
    def test_continuous_travel_is_not_reassigned(self):
        core = _core()
        _, command = _job(core)
        _feedback(core, command, 0, 0.0)
        for now in range(1, 71):
            _feedback(core, command, now, float(now))   # 1 m/s 持续在途
            core._subtask_monitor(now)
        reasons = [row.get("reason") for row in core.audit
                   if row.get("kind") == "subtask_deviation"]
        self.assertNotIn("arrival_timeout", reasons)

    def test_stuck_platform_still_times_out(self):
        core = _core()
        _, command = _job(core)
        _feedback(core, command, 0, 0.0)
        for now in range(1, 71):
            _feedback(core, command, now, 0.0)          # 有反馈但没位移
            core._subtask_monitor(now)
        rows = [row for row in core.audit
                if row.get("kind") == "subtask_deviation"]
        self.assertTrue(any(row.get("reason") == "arrival_timeout"
                            for row in rows))

    def test_stop_after_moving_uses_last_movement_time(self):
        core = _core()
        _, command = _job(core)
        _feedback(core, command, 0, 0.0)
        for now in range(1, 41):
            _feedback(core, command, now, float(now))
            core._subtask_monitor(now)
        stopped = core.subtask_states["T1-S1"].get("moved_at")
        self.assertEqual(stopped, 40)
        for now in range(41, 76):
            _feedback(core, command, now, 40.0)          # 40 s 起不再动
            core._subtask_monitor(now)
        rows = [row for row in core.audit
                if row.get("kind") == "subtask_deviation"
                and row.get("reason") == "arrival_timeout"]
        self.assertTrue(rows)
        self.assertGreaterEqual(rows[0]["sim_s"], 70)


if __name__ == "__main__":
    unittest.main()
