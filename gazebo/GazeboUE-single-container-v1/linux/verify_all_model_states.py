"""Run the aggregate model-states verifier inside every Gazebo container."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import time


def verify(index, timeout):
    name = f"wangdazhe-gazebo-jazzy-container_{index:02d}"
    process = subprocess.run(
        [
            "docker",
            "exec",
            name,
            "bash",
            "-lc",
            (
                "source /opt/ros/jazzy/setup.bash; "
                "python3 /opt/gazebo_ue/linux/verify_model_states.py "
                f"--timeout {timeout}"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=timeout + 5,
    )
    try:
        details = json.loads(process.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        details = {"passed": False, "received": 0, "missing": []}
    return {
        "container": name,
        "returncode": process.returncode,
        "stderr": process.stderr.strip(),
        **details,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument(
        "--output", default="runtime/acceptance/model_states_topics.json"
    )
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=args.instances) as executor:
        results = list(executor.map(
            lambda index: verify(index, args.timeout), range(args.instances)
        ))
    report = {
        "checked_at_unix": time.time(),
        "instances_expected": args.instances,
        "instances_passed": sum(item["passed"] for item in results),
        "model_states_expected": args.instances * 50,
        "model_states_received": sum(item["received"] for item in results),
        "passed": all(item["passed"] for item in results),
        "instances": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
