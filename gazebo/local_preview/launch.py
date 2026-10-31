"""Windows entry point: resolve the script path and preserve actionable logs."""
from datetime import datetime
from pathlib import Path
import subprocess
import sys


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    here = Path(__file__).resolve().parent
    action = sys.argv[1:]
    logs = here / 'runtime'
    logs.mkdir(exist_ok=True)
    logfile = logs / ('launch_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.log')
    resolved = subprocess.run(['wsl.exe', '-d', 'Ubuntu', '--exec', 'wslpath', '-a', (here / 'preview.py').as_posix()],
                              capture_output=True, encoding='utf-8', errors='replace')
    if resolved.returncode:
        print(resolved.stderr)
        return resolved.returncode
    print('Action:', ' '.join(action), flush=True)
    print('Log:', logfile, flush=True)
    with logfile.open('w', encoding='utf-8') as log:
        child = subprocess.Popen(['wsl.exe', '-d', 'Ubuntu', '--exec', '/usr/bin/python3', '-u', resolved.stdout.strip(), *action],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace')
        for line in child.stdout:
            log.write(line)
            log.flush()
            print(line, end='', flush=True)
        result = child.wait()
    print('Completed.' if result == 0 else 'Failed. See the log above.', flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
