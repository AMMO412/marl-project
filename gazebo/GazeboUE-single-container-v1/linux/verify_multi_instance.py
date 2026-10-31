"""Verify that every Gazebo instance publishes all 50 robot poses over TCP."""

import argparse
import json
import socket
import threading
import time
from pathlib import Path


def verify_instance(host, port, index, timeout, result):
    expected_instance = f"container_{index:02d}"
    expected_robots = {f"robot_{number:03d}" for number in range(1, 51)}
    robots = set()
    errors = []
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=5) as connection:
            connection.settimeout(1)
            buffer = b""
            while time.monotonic() - started < timeout and robots != expected_robots:
                try:
                    chunk = connection.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    errors.append("connection closed before all poses arrived")
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line:
                        continue
                    packet = json.loads(line)
                    if packet.get("instance_id") != expected_instance:
                        errors.append(
                            f"unexpected instance_id={packet.get('instance_id')!r}"
                        )
                        continue
                    robot = packet.get("robot_name")
                    if robot in expected_robots:
                        robots.add(robot)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    missing = sorted(expected_robots - robots)
    result[index] = {
        "instance_id": expected_instance,
        "port": port,
        "received": len(robots),
        "missing": missing,
        "errors": errors,
        "passed": not missing and not errors,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--instances", type=int, default=20)
    parser.add_argument("--base-port", type=int, default=18765)
    parser.add_argument("--port-stride", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument(
        "--output", default="runtime/acceptance/multi_instance_poses.json"
    )
    args = parser.parse_args()

    results = {}
    threads = []
    for index in range(args.instances):
        port = args.base_port + index * args.port_stride
        thread = threading.Thread(
            target=verify_instance,
            args=(args.host, port, index, args.timeout, results),
        )
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()

    ordered = [results[index] for index in range(args.instances)]
    report = {
        "checked_at_unix": time.time(),
        "instances_expected": args.instances,
        "instances_passed": sum(item["passed"] for item in ordered),
        "poses_expected": args.instances * 50,
        "poses_received": sum(item["received"] for item in ordered),
        "passed": all(item["passed"] for item in ordered),
        "instances": ordered,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
