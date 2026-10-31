"""Restart manually killed Gazebo containers for the configured desired scale."""

import fcntl
import json
import signal
import subprocess
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DESIRED_COUNT_FILE = PROJECT_ROOT / "desired_instance_count"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
POLL_SECONDS = 1.0
PREFIX = "wangdazhe-gazebo-jazzy-container_"
STOP = False


def log(event, **fields):
    record = {"time": time.time(), "event": event, **fields}
    print(json.dumps(record, ensure_ascii=False), flush=True)


def desired_names():
    try:
        count = int(DESIRED_COUNT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        log("invalid_desired_count", error=str(exc))
        return []
    if not 0 <= count <= 20:
        log("invalid_desired_count", count=count)
        return []
    return [f"{PREFIX}{index:02d}" for index in range(count)]


def running_states(names):
    if not names:
        return {}
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Name}}|{{.State.Running}}", *names],
        capture_output=True,
        text=True,
    )
    states = {}
    for line in result.stdout.splitlines():
        if "|" not in line:
            continue
        name, running = line.lstrip("/").split("|", 1)
        states[name] = running.strip().lower() == "true"
    if result.returncode:
        log("inspect_error", stderr=result.stderr.strip())
    return states


def scan_once():
    names = desired_names()
    states = running_states(names)
    for name in names:
        if states.get(name, False):
            continue
        started = subprocess.run(["docker", "start", name], capture_output=True, text=True)
        log(
            "restart_attempt",
            container=name,
            success=started.returncode == 0,
            stdout=started.stdout.strip(),
            stderr=started.stderr.strip(),
        )


def request_stop(_signum, _frame):
    global STOP
    STOP = True


def main():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = RUNTIME_DIR / "container_watchdog.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        log("watchdog_started", desired_count_file=str(DESIRED_COUNT_FILE))
        while not STOP:
            started = time.monotonic()
            scan_once()
            remaining = POLL_SECONDS - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
        log("watchdog_stopped")


if __name__ == "__main__":
    main()
