"""动态场景 20 回合子任务时序冲突消解率（2.2(3)）。"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from interop.message import parse_message
from interop.runtime import InteropPlanner, to_v2_dict
from interop.timing_resolution import (TimingResolutionTracker, TimingSlot,
                                      detect_timing_conflicts)
from run_demo_v2 import simulate


def slot(sid, start, end, *, unit="rover_01", window=(0, 200), deps=(),
         coord=(), state="PLANNED", parent=None, travel=0.0, assigned=True):
    return TimingSlot(sid, parent or sid, "T-RCN", {}, start, end,
                      window[0], window[1], list(deps), list(coord),
                      unit_id=unit, state=state, travel_s=travel,
                      assigned=assigned)


def _ugv(no, capabilities=None, speed=8.0, sensor=None, payload_kg=600.0):
    unit = dict(unit_id="U%d" % no, platform_type="ifv", platform_class="UGV",
                robot_id=no, capabilities=capabilities or {
                    "RCN": 2, "STK": 1, "PTL": 2, "HLD": 2},
                position={"x": 0, "y": 0}, altitude_m=0.0,
                vertical_speed_mps=0.0, heading_rad=0.0, speed_mps=speed,
                endurance_s=21600.0, status="READY", payload_kg=payload_kg)
    if sensor is not None:
        unit["sensor"] = sensor
    return unit


def _message(count=2, duration=40, end_s=300, capability=1):
    return dict(
        schema_version="0.3", message_id="MSG-TIMING",
        issued_at="2026-11-09T08:00:00Z", source="UPPER",
        tasks=[dict(task_id="T%d" % i, task_type="T-RCN", priority=i,
                    target={"target_list": [[10 * i, 0]]},
                    window={"start_s": 0, "end_s": end_s},
                    required_capabilities={"RCN": capability},
                    min_units=1, max_units=1,
                    params={"duration_s": duration})
               for i in range(1, count + 1)])


def _formation(units):
    return dict(formation=dict(formation_id="F-TIMING", units=units),
                constraints=[], meta={"cell_size_m": 1.0,
                                      "plan_id": "P-TIMING"})


def _run(message, formation, timeline, k=10, max_ticks=700):
    parsed = parse_message(message, formation)
    data = to_v2_dict(parsed, message, formation)
    data["K"] = k
    data["timeline"] = timeline
    planner = InteropPlanner(parsed, objective="makespan", data=data)
    report, audit = simulate(data, mode="normal", motion="teleport", avoid=False,
                             behavior=False, max_ticks=max_ticks, planner=planner)
    return report


class DetectorTests(unittest.TestCase):
    def test_four_conflict_types(self):
        overlap = detect_timing_conflicts([
            slot("A", 0, 20, unit="rover_01"),
            slot("B", 10, 30, unit="rover_01")])
        self.assertIn("RESOURCE_OVERLAP", [hit.type for hit in overlap])

        dependency = detect_timing_conflicts([
            slot("A", 0, 20, parent="T1"),
            slot("B", 15, 35, deps=["A"], parent="T2")])
        self.assertIn("DEPENDENCY", [hit.type for hit in dependency])

        window = detect_timing_conflicts([
            slot("A", 90, 120, window=(0, 100))])
        self.assertIn("WINDOW", [hit.type for hit in window])

        coordination = detect_timing_conflicts([
            slot("A", 0, 20, parent="G", coord=("simultaneous_arrival",)),
            slot("B", 5, 25, parent="G", coord=("simultaneous_arrival",))])
        self.assertIn("COORDINATION", [hit.type for hit in coordination])

    def test_clean_schedule_has_no_conflict(self):
        self.assertEqual(detect_timing_conflicts([
            slot("A", 0, 20, unit="rover_01"),
            slot("B", 25, 45, unit="rover_01", travel=3.0)]), [])


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.bad = [slot("A", 0, 20, unit="rover_01", parent="T1"),
                    slot("B", 10, 30, unit="rover_01", parent="T2")]
        self.fixed = [slot("A", 0, 20, unit="rover_01", parent="T1"),
                      slot("B", 30, 50, unit="rover_01", parent="T2")]

    def test_resolution_candidate_is_confirmed_then_counted(self):
        tracker = TimingResolutionTracker(budget=20, round_steps=1)
        tracker.observe(self.bad, 0, phase="detect")
        self.assertTrue(tracker.has_open())
        tracker.observe(self.fixed, 1, phase="verify", repaired=True)
        self.assertFalse(tracker.has_open())
        tracker.observe(self.fixed, 2, phase="detect")
        result = tracker.result(3)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(result["rate"], 1.0)
        self.assertEqual(result["by_round"]["1"], 1.0)

    def test_continuous_conflict_counts_once_and_expires(self):
        tracker = TimingResolutionTracker(budget=20, round_steps=1)
        for t in range(22):
            tracker.observe(self.bad, t, phase="detect")
        self.assertEqual(len(tracker.records), 1)
        result = tracker.result(22)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["resolved"], 0)
        self.assertEqual(result["expired"], 1)
        self.assertEqual(result["rate"], 0.0)

    def test_deleted_or_unassigned_is_not_a_resolution(self):
        tracker = TimingResolutionTracker(budget=20, round_steps=1)
        tracker.observe(self.bad, 0, phase="detect")
        for t in range(1, 22):
            tracker.observe(self.fixed, t, phase="verify", repaired=True,
                            deleted={"T2"})
        result = tracker.result(22)
        self.assertEqual(result["resolved"], 0)
        self.assertEqual(result["abandoned"], 1)
        self.assertEqual(result["rate"], 0.0)

    def test_reappearance_after_resolution_is_a_new_conflict(self):
        tracker = TimingResolutionTracker(budget=20, round_steps=1)
        tracker.observe(self.bad, 0, phase="detect")
        tracker.observe(self.fixed, 1, phase="verify", repaired=True)
        tracker.observe(self.fixed, 2, phase="detect")
        tracker.observe(self.bad, 3, phase="detect")
        self.assertEqual(len(tracker.records), 2)
        tracker.observe(self.fixed, 4, phase="verify", repaired=True)
        tracker.observe(self.fixed, 5, phase="detect")
        result = tracker.result(6)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["resolved"], 2)


class IntegrationTests(unittest.TestCase):
    def test_single_platform_delay_records_conflict_and_budget(self):
        report = _run(
            _message(count=2), _formation([_ugv(1)]),
            [dict(t=5, event="job_slow", job_id="T1", factor=0.05)],
            k=10, max_ticks=300)
        timing = report["scheduler_timing_resolution"]
        self.assertFalse(timing["no_conflict"])
        self.assertGreaterEqual(len(timing["conflicts"]), 1)
        self.assertIn("by_round", timing)
        self.assertIn("conflicts", timing)
        for item in timing["conflicts"]:
            self.assertIn(item["type"], ("RESOURCE_OVERLAP", "DEPENDENCY",
                                         "WINDOW", "COORDINATION"))

    def test_fifteen_platform_batch_does_not_count_abandoned_as_resolved(self):
        import random
        tasks = [dict(task_id="T%d" % i, task_type="T-RCN",
                      priority=min(i, 5),
                      target={"target_list": [[10 * i, 0], [10 * i, 5]]},
                      window={"start_s": 0, "end_s": 2000},
                      required_capabilities={},
                      min_units=2, max_units=2,
                      params={"duration_s": 30,
                              "sensor_required": {"type": "sar",
                                                  "min_range_m": 6000.0}}) for i in range(1, 8)]
        message = dict(schema_version="0.3", message_id="MSG-TIMING-15",
                       issued_at="2026-11-09T08:00:00Z", source="UPPER",
                       tasks=tasks)
        units = [_ugv(no, capabilities={"RCN": 3 if no <= 5 else 1,
                                        "STK": 1, "PTL": 2, "HLD": 2},
                      sensor=({"type": "sar", "range_m": 8000.0,
                               "fov_deg": 120.0, "resolution_m": 1.0}
                              if no <= 5 else None))
                 for no in range(1, 16)]
        formation = _formation(units)
        self.assertEqual(len(units), 15)
        total = resolved = 0
        samples = []
        for seed in (1, 2, 3):
            rng = random.Random(seed)
            factors = [round(rng.uniform(0.10, 0.30), 2) for _ in range(3)]
            timeline = [dict(t=5 + 10 * i, event="job_slow",
                             job_id="T%d" % (i + 1), factor=factors[i])
                        for i in range(3)]
            report = _run(message, formation, timeline, k=10, max_ticks=700)
            timing = report["scheduler_timing_resolution"]
            self.assertFalse(timing["no_conflict"], seed)
            total += timing["total"]
            resolved += timing["resolved"]
            samples.append((seed, factors, timing["total"], timing["resolved"]))
            measured = [c for c in timing['conflicts']
                        if c['status'] in ('resolved', 'expired')]
            self.assertEqual(timing['total'], len(measured))
            self.assertEqual(timing['resolved'], sum(c['status']=='resolved' for c in measured))
        if not total:
            self.assertIsNone(timing['rate'])


if __name__ == '__main__':
    unittest.main()
