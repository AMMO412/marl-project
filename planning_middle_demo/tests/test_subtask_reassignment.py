"""子任务级偏差/失败判定与编成内局部改派（2.1(4)）。"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from interop.message import parse_message
from interop.runtime import InteropPlanner, to_v2_dict
from run_demo_v2 import simulate


def _ugv(no, x=0.0, y=0.0, speed=8.0, unit_id=None):
    return dict(unit_id=unit_id or ("U%d" % no), platform_type="ifv",
                platform_class="UGV",
                robot_id=no, capabilities={"RCN": 2, "STK": 1, "PTL": 2, "HLD": 2},
                position={"x": x, "y": y}, altitude_m=0.0,
                vertical_speed_mps=0.0, heading_rad=0.0, speed_mps=speed,
                endurance_s=21600.0, status="READY")


def _message(duration=40, end_s=140):
    return dict(
        schema_version="0.3", message_id="MSG-SUBTASK-1",
        issued_at="2026-11-09T08:00:00Z", source="UPPER",
        tasks=[dict(
            task_id="T1", task_type="T-RCN", priority=1,
            target={"target_list": [[10, 0], [20, 0]]},
            window={"start_s": 0, "end_s": end_s},
            required_capabilities={"RCN": 1}, min_units=1, max_units=2,
            params={"duration_s": duration})])


def _formation(platforms):
    return dict(
        formation=dict(formation_id="F-SUBTASK", units=platforms),
        constraints=[], meta={"cell_size_m": 1.0, "plan_id": "P-SUBTASK"})


def _run(message, formation, timeline=None, behavior=False, motion="teleport",
         max_ticks=120, nav=None):
    parsed = parse_message(message, formation)
    data = to_v2_dict(parsed, message, formation)
    if timeline:
        data["timeline"] = timeline
    planner = InteropPlanner(parsed, objective="makespan", data=data)
    report, audit = simulate(data, mode="normal", motion=motion, avoid=False,
                             behavior=behavior, max_ticks=max_ticks,
                             planner=planner, nav=nav)
    return report, audit, parsed


def _subtask_rows(audit):
    return [row for row in audit
            if str(row.get("kind", "")).startswith("subtask_")]


class LocalReplacementTests(unittest.TestCase):
    def test_whole_attempt_failure_does_not_spawn_individual_replacements(self):
        message=json.loads((ROOT/'tests/fixtures/colleague5/crossroad_recon.message.json').read_text(encoding='utf-8-sig'))
        formation=json.loads((ROOT/'tests/fixtures/colleague5/crossroad_recon.formation.json').read_text(encoding='utf-8-sig'))
        message['tasks'][0]['params'].update(search_deadline_s=4,duration_s=4)
        message['tasks'][0]['window']['end_s']=80
        formation['formation']['units'].extend([_ugv(3,unit_id='SPARE-3'),_ugv(4,unit_id='SPARE-4')])
        from interop.runtime import nav_from_scenario
        report,audit,_=_run(message,formation,behavior=True,motion='real',max_ticks=30,
            nav=nav_from_scenario(parse_message(message,formation)))
        self.assertEqual(report['jobs'][0]['attempts'],2)
        self.assertEqual(report['jobs'][0]['status'],'failed')
        self.assertFalse(any(row['kind']=='subtask_reassigned' for row in audit))

    def test_member_loss_replaces_only_the_failed_slot(self):
        message = _message()
        formation = _formation([_ugv(1), _ugv(2), _ugv(3), _ugv(4)])
        report, audit, _ = _run(
            message, formation,
            timeline=[dict(t=20, event="member_lost", robot_no=1)])
        rows = _subtask_rows(audit)
        failed = [row for row in rows if row["kind"] == "subtask_failed"]
        moved = [row for row in rows if row["kind"] == "subtask_reassigned"]
        self.assertEqual([(row["subtask_id"], row["pid"]) for row in failed],
                         [("T1-S1", "rover_01")])
        self.assertEqual(len(moved), 1)
        self.assertEqual((moved[0]["old_pid"], moved[0]["new_pid"]),
                         ("rover_01", "rover_03"))
        self.assertTrue(report["all_succeeded"])
        self.assertEqual(report["subtask_reassignments"], 1)
        states = {item["subtask_id"]: item for item in report["subtasks"]}
        self.assertEqual(states["T1-S1"]["status"], "succeeded")
        self.assertEqual(states["T1-S1"]["reassignments"], 1)
        self.assertEqual(states["T1-S2"]["reassignments"], 0)

        # 其它席位不中断：rover_02 的原指令没有收到 cancel，一直跑到作业结束。
        sibling = "demo-v2:T1:1:rover_02"
        cancelled = [row for row in audit
                     if row.get("kind") == "feedback_applied"
                     and row["event"].get("command_id") == sibling
                     and row["event"].get("status") == "cancelled"]
        self.assertEqual(cancelled, [])
        finished = [row["sim_s"] for row in audit
                    if row.get("kind") == "attempt_finished"
                    and row["command_id"] == sibling]
        self.assertEqual(len(finished), 1)
        baseline, baseline_audit, _ = _run(message, formation)
        sibling_finished = [row['sim_s'] for row in baseline_audit
                            if row.get('kind') == 'attempt_finished'
                            and row['command_id'] == sibling]
        self.assertGreaterEqual(finished[0], sibling_finished[0])

    def test_no_spare_falls_back_to_whole_task_requeue(self):
        message = _message()
        formation = _formation([_ugv(1), _ugv(2)])
        report, audit, _ = _run(
            message, formation,
            timeline=[dict(t=20, event="member_lost", robot_no=1)])
        self.assertFalse([row for row in audit
                          if row["kind"] == "subtask_reassigned"])
        requeued = [row for row in audit if row["kind"] == "job_requeued"]
        self.assertTrue(requeued)
        self.assertEqual(requeued[0]["cause"], "subtask_restart")
        # 没有替补时不允许把任务“悄悄算完成”；至少尝试过一次整组重排。
        self.assertGreaterEqual(report["jobs"][0]["attempts"], 1)

    def test_terminal_recon_failure_retries_then_fails(self):
        message = json.loads((ROOT / "tests/fixtures/colleague5/crossroad_recon.message.json")
                             .read_text(encoding="utf-8-sig"))
        formation = json.loads((ROOT / "tests/fixtures/colleague5/crossroad_recon.formation.json")
                               .read_text(encoding="utf-8-sig"))
        message["tasks"][0]["params"]["search_deadline_s"] = 4
        message["tasks"][0]["params"]["duration_s"] = 4
        message["tasks"][0]["window"]["end_s"] = 80
        from interop.runtime import nav_from_scenario
        parsed = parse_message(message, formation)
        nav = nav_from_scenario(parsed)
        report, audit, _ = _run(message, formation, behavior=True,
                                motion="real", max_ticks=30, nav=nav)
        job = report["jobs"][0]
        self.assertEqual(job["attempts"], 2)
        self.assertEqual(job["status"], "failed")
        causes = [row["cause"] for row in audit if row["kind"] == "job_requeued"]
        self.assertTrue(causes)
        terminal = [row for row in audit if row["kind"] == "subtask_failed"]
        self.assertTrue(terminal)
        self.assertTrue(all(row["terminal"] for row in terminal))


class BehaviorReconReplacementTests(unittest.TestCase):
    def test_recon_sector_reassigned_without_stopping_other_sectors(self):
        message = json.loads((ROOT / "tests/fixtures/colleague5/crossroad_recon.message.json")
                             .read_text(encoding="utf-8-sig"))
        formation = json.loads((ROOT / "tests/fixtures/colleague5/crossroad_recon.formation.json")
                               .read_text(encoding="utf-8-sig"))
        message["tasks"][0]["max_units"] = 5
        message["tasks"][0]["window"]["end_s"] = 260
        message["tasks"][0]["params"]["_slot_units"] = {
            'search:%d/1' % i: 'U%d' % i for i in range(1, 5)}
        formation["formation"]["units"].append(_ugv(3, x=10, y=68, speed=6,
                                                    unit_id="U5"))
        from interop.runtime import nav_from_scenario
        parsed = parse_message(message, formation)
        nav = nav_from_scenario(parsed)
        report, audit, _ = _run(
            message, formation,
            timeline=[dict(t=2, event="member_lost", robot_no=1)],
            behavior=True, motion="real", max_ticks=200, nav=nav)
        moved = [row for row in audit if row["kind"] == "subtask_reassigned"]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]["subtask_id"], "T1-S1")
        self.assertEqual((moved[0]["old_pid"], moved[0]["new_pid"]),
                         ("rover_01", "rover_03"))
        states = {item["subtask_id"]: item for item in report["subtasks"]}
        self.assertEqual(states["T1-S1"]["reassignments"], 1)
        for sid in ("T1-S2", "T1-S3", "T1-S4"):
            self.assertEqual(states[sid]["reassignments"], 0)
            self.assertEqual(states[sid]["status"], "succeeded")
        self.assertTrue(report["all_succeeded"])


class BehaviorPatrolReplacementTests(unittest.TestCase):
    def test_patrol_checkpoint_slot_reassigned(self):
        message = json.loads((ROOT / "tests/fixtures/colleague5/area_patrol.message.json")
                             .read_text(encoding="utf-8-sig"))
        formation = json.loads((ROOT / "tests/fixtures/colleague5/area_patrol.formation.json")
                               .read_text(encoding="utf-8-sig"))
        message["tasks"][0]["max_units"] = 5
        message["tasks"][0]["params"]["cycles"] = 1
        message["tasks"][0]["window"]["end_s"] = 200
        formation["formation"]["units"].append(_ugv(3, x=-96, y=-60,
                                                    unit_id="U5"))
        from interop.runtime import nav_from_scenario
        parsed = parse_message(message, formation)
        nav = nav_from_scenario(parsed)
        report, audit, _ = _run(
            message, formation,
            timeline=[dict(t=20, event="member_lost", robot_no=1)],
            behavior=True, motion="real", max_ticks=160, nav=nav)
        moved = [row for row in audit if row["kind"] == "subtask_reassigned"]
        self.assertEqual(len(moved), 1)
        self.assertEqual((moved[0]["old_pid"], moved[0]["new_pid"]),
                         ("rover_01", "rover_03"))
        self.assertTrue(report["all_succeeded"])
        states = {item["subtask_id"]: item for item in report["subtasks"]}
        self.assertEqual(states["T1-S1"]["reassignments"], 1)
        for sid, item in states.items():
            if sid != "T1-S1":
                self.assertEqual(item["reassignments"], 0)


if __name__ == '__main__':
    unittest.main()
