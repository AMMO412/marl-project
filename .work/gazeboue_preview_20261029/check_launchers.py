"""End-to-end Windows CMD checks against the live local Gazebo preview."""
from pathlib import Path
import json
import subprocess
import time

root = Path(__file__).resolve().parents[2]
base = root / 'gazebo'
results = []


def run(name, timeout=120):
    start = time.monotonic()
    result = subprocess.run(['cmd.exe', '/d', '/c', str(base / name)], input='\n',
                            capture_output=True, encoding='utf-8', errors='replace', timeout=timeout,
                            cwd=str(Path.home()), creationflags=subprocess.CREATE_NO_WINDOW)
    record = dict(script=name, code=result.returncode, elapsed=time.monotonic()-start,
                  output=result.stdout + result.stderr)
    results.append(record)
    print(json.dumps(record, ensure_ascii=True), flush=True)
    if result.returncode:
        raise RuntimeError(name + ' failed')
    return record


try:
    run('关闭Gazebo预览.cmd')
    run('打开Gazebo预览.cmd')
    run('查看场景全貌.cmd')
    run('回到机器人近景.cmd')
    # Start the exact double-click command, then interrupt it with the stop CMD.
    movement = subprocess.Popen(['cmd.exe', '/d', '/c', str(base / '移动1号机器人.cmd')],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(4)
    run('停止1号机器人.cmd')
    output = movement.communicate(input='\n', timeout=20)[0]
    record = dict(script='移动1号机器人.cmd', code=movement.returncode, output=output)
    results.append(record)
    print(json.dumps(record, ensure_ascii=True), flush=True)
    assert movement.returncode == 0
    assert 'Movement cancelled by stop request.' in output
    run('打开Gazebo预览.cmd')  # repeated open must reuse the visible window
finally:
    (Path(__file__).parent / 'launcher_checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
