"""Verify that a workbench run exports an auditable command/feedback chain."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workbench_server
from chain_trace import verify_chain


class ChainTraceTests(unittest.TestCase):
    def test_workbench_export_links_actual_commands_feedback_and_topics(self):
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp) / "outputs"
            output_root.mkdir()
            out = output_root / "workbench_chain_test"
            out.mkdir()
            (out / "request.json").write_text(json.dumps(dict(
                scenario="interop_patrol",
                planner="interop",
                motion="real",
                avoid=True,
                behavior=True,
                task_seed=1,
                reseed_on_run=False,
                max_ticks=20,
            )), encoding="utf-8")
            with patch.object(workbench_server, "OUTPUTS", output_root):
                workbench_server.run_worker(out)

            required = {
                "chain_viewer.html", "chain_summary.json",
                "chain_verification.json", "chain_raw.json",
                "initial_config.json", "final_config.json",
                "ros2_plan_node.py",
            }
            self.assertTrue(required.issubset(
                {path.name for path in out.iterdir()}))
            summary = json.loads((out / "chain_summary.json").read_text(
                encoding="utf-8"))
            verification = json.loads(
                (out / "chain_verification.json").read_text(
                    encoding="utf-8"))
            self.assertTrue(summary["passed"], verification)
            self.assertEqual(summary["run_id"], out.name)
            self.assertGreater(summary["commands"], 0)
            self.assertGreater(summary["feedback"], 0)

            archive = out / "archive"
            commands = [
                json.loads(line) for line in
                (archive / "commands.jsonl").read_text(
                    encoding="utf-8").splitlines() if line.strip()
            ]
            feedback = [
                json.loads(line) for line in
                (archive / "feedback.jsonl").read_text(
                    encoding="utf-8").splitlines() if line.strip()
            ]
            starts = [row for row in commands if row["action"] == "start"]
            self.assertTrue(starts)
            self.assertTrue(all(row["subtask_id"] for row in starts))
            self.assertTrue(all(
                row["topic"].startswith("/container_00/robot_")
                and row["topic"].endswith("/cmd_vel")
                for row in commands))
            by_id = {row["command_id"]: row for row in commands}
            self.assertTrue(feedback)
            for row in feedback:
                command = by_id[row["command_id"]]
                self.assertEqual(row["task_id"], command["task_id"])
                self.assertEqual(row["worker_id"], command["worker_id"])
                self.assertEqual(row["attempt"], command["attempt"])

            report = json.loads((out / "report.json").read_text(
                encoding="utf-8"))
            self.assertTrue(report["chain_verification"]["passed"])
            manifest = json.loads((out / "manifest.json").read_text(
                encoding="utf-8"))
            self.assertTrue(manifest["chain"]["passed"])
            self.assertIn("ros2_plan_node.py", manifest["plan_files"])
            self.assertTrue(verify_chain(out)["passed"])

            raw_path = out / "chain_raw.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            self.assertTrue(raw["planning"])
            for row in raw["planning"]:
                row["runtime_plan_id"] = "legacy-field-must-not-be-used"
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertTrue(verify_chain(out)["passed"])

            for row in raw["planning"]:
                row["plan_id"] = "wrong-plan-version"
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            verification = verify_chain(out)
            self.assertFalse(verification["passed"])
            self.assertIn("C2", verification["failed_checks"])


if __name__ == "__main__":
    unittest.main()
